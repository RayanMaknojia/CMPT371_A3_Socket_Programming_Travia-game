"""
CMPT 371 A3: Multiplayer Trivia Server
Architecture: TCP Sockets with Multithreaded Session Management
Protocol: JSON over TCP with \n message boundary delimiter

Key design decisions:
  - Matchmaking queue holds clients until 2 are ready to form a session.
  - Each GameSession runs on its own daemon thread so concurrent games
    never block the main accept loop.
  - Player names are collected in PARALLEL (one thread per player) so
    neither player has to wait for the other to finish typing.
  - A dedicated receiver thread per player detects disconnects mid-game
    and notifies the surviving player immediately.
"""

import socket
import threading
import json
import random
import time

# -------------- Server configuration 
HOST = '0.0.0.0'   # Listen on all interfaces so LAN clients can connect
PORT = 5556

# Shared matchmaking queue – protected by a lock because multiple accept
# threads could theoretically append at the same moment.
matchmaking_queue = []
queue_lock = threading.Lock()

# -------------- Question bank 
QUESTIONS = [
    ("Capital of France?",          "paris"),
    ("5 + 7?",                       "12"),
    ("Color of the sky?",            "blue"),
    ("2 * 6?",                       "12"),
    ("Largest planet in solar system?", "jupiter"),
    ("Fastest land animal?",         "cheetah"),
    ("Water freezes at (°C)?",       "0"),
    ("Opposite of hot?",             "cold"),
    ("Square root of 9?",            "3"),
    ("Red + Blue mixed gives?",      "purple"),
]

ANSWER_TIMEOUT = 20   # Seconds each player has to answer before time-out
NUM_QUESTIONS  = 10   # How many questions to ask per game


# -------------- Helper I/O functions 

def send_json(conn, data):
    """
    Serialize `data` to JSON, append the \n boundary, and send over TCP.
    The newline acts as an application-layer message delimiter so the client
    can split a buffered TCP stream into individual messages reliably.
    """
    msg = json.dumps(data) + "\n"
    conn.sendall(msg.encode('utf-8'))


def recv_json(conn):
    """
    Receive raw bytes, decode, strip, and parse the FIRST complete JSON
    message (delimited by \n).  Returns None if the connection was closed.

    """
    try:
        data = conn.recv(4096).decode('utf-8')
        if not data:
            return None   # Clean disconnect
        # Take only the first complete message from a potentially batched buffer
        first = data.strip().split("\n")[0]
        return json.loads(first)
    except (ConnectionResetError, OSError, json.JSONDecodeError):
        return None


# -------------- Session logic 

def collect_name(conn, result_container, key):
    """
    Ask one player for their display name and store it in result_container[key].
    Runs on its own thread so BOTH players are asked simultaneously.

    """
    try:
        send_json(conn, {"type": "NAME"})        # Prompt the client for a name
        msg = recv_json(conn)
        result_container[key] = msg["name"] if msg else None
    except Exception:
        result_container[key] = None


def game_session(p1, p2):
    """
    Isolated game loop for two matched players.
    Runs entirely on a background daemon thread so it never blocks the
    main server accept loop or any other session.

    Flow:
      1. Collect names in parallel.
      2. Broadcast START so both UIs advance at the same time.
      3. Loop through questions; collect answers with a per-player timeout.
      4. Send ROUND_RESULT after each question so clients can show feedback.
      5. Send END with the final leaderboard.
      6. Handle mid-game disconnects gracefully at every step.
    """
    print("[GAME] Session started")

    try:
        # -------------- Step 1: Collect names in parallel 
        names = {}   # Will be populated by the two collector threads

        t_name1 = threading.Thread(target=collect_name, args=(p1, names, "p1"))
        t_name2 = threading.Thread(target=collect_name, args=(p2, names, "p2"))
        t_name1.start()
        t_name2.start()
        t_name1.join()
        t_name2.join()

        # If either player disconnected before sending their name, abort.
        if names.get("p1") is None or names.get("p2") is None:
            # Notify the surviving player if the other vanished during setup
            _handle_early_disconnect(p1, p2, names)
            return

        name1, name2 = names["p1"], names["p2"]
        scores = {name1: 0, name2: 0}
        print(f"[GAME] {name1} vs {name2}")

        # -------------- Step 2: Broadcast START to both clients simultaneously 
        # Both clients receive START at roughly the same time so their UIs
        # transition to the game screen together.
        send_json(p1, {"type": "START", "opponent": name2})
        send_json(p2, {"type": "START", "opponent": name1})

        # -------------- Step 3 & 4: Question loop 
        q_list = random.sample(QUESTIONS, NUM_QUESTIONS)

        for i, (question_text, correct_answer) in enumerate(q_list, start=1):

            # Send the same question to both players at the same time
            q_msg = {"type": "QUESTION", "q": question_text,
                     "progress": f"{i}/{NUM_QUESTIONS}"}
            send_json(p1, q_msg)
            send_json(p2, q_msg)

            # Collect answers concurrently with a 20-second server-side timeout
            answers = {}   # {name: answer_string | None}

            def get_answer(player_conn, player_name):
                """
                Wait up to ANSWER_TIMEOUT seconds for this player's answer.
                Stores None on timeout or disconnect so the main loop can
                handle it without crashing.
                """
                try:
                    player_conn.settimeout(ANSWER_TIMEOUT)
                    msg = recv_json(player_conn)
                    # Detect a clean disconnect (recv returned None)
                    answers[player_name] = msg["answer"] if msg else None
                except socket.timeout:
                    answers[player_name] = None   # Time ran out
                except (OSError, ConnectionResetError):
                    answers[player_name] = None   # Unexpected disconnect
                finally:
                    player_conn.settimeout(None)  # Reset to blocking mode

            t1 = threading.Thread(target=get_answer, args=(p1, name1))
            t2 = threading.Thread(target=get_answer, args=(p2, name2))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # -------------- Disconnect detection mid-question 
            # If a player's answer is None AND their socket is dead, it means
            # they disconnected (vs just timing out on a live connection).
            p1_alive = _is_connected(p1)
            p2_alive = _is_connected(p2)

            if not p1_alive:
                # p1 dropped – notify p2 and end the session
                send_json(p2, {
                    "type": "OPPONENT_LEFT",
                    "message": f"{name1} has left the game. YOU WIN!",
                    "your_score": scores[name2]
                })
                print(f"[DISCONNECT] {name1} left mid-game")
                return

            if not p2_alive:
                send_json(p1, {
                    "type": "OPPONENT_LEFT",
                    "message": f"{name2} has left the game. YOU WIN!",
                    "your_score": scores[name1]
                })
                print(f"[DISCONNECT] {name2} left mid-game")
                return

            # --------------- Score and build result strings 
            results = {}
            for name, answer in answers.items():
                if answer is not None and answer.strip().lower() == correct_answer:
                    scores[name] += 1
                    results[name] = f"✓ Correct! (+1)"
                elif answer is None:
                    results[name] = f"✗ Time's up! (Answer: {correct_answer})"
                else:
                    results[name] = f"✗ Wrong! (Answer: {correct_answer})"

            # ----------- Broadcast round result to both players 
            send_json(p1, {
                "type": "ROUND_RESULT",
                "you":      results[name1],
                "opponent": results[name2],
                "your_score":     scores[name1],
                "opponent_score": scores[name2],
            })
            send_json(p2, {
                "type": "ROUND_RESULT",
                "you":      results[name2],
                "opponent": results[name1],
                "your_score":     scores[name2],
                "opponent_score": scores[name1],
            })

            # Hold on the result screen for 4 seconds before sending the next
            # question.  Both clients stay in sync because neither receives
            # the next QUESTION message until this sleep completes.
            time.sleep(4)

        # --------------- Step 5: End of game - send leaderboard 
        leaderboard = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        end_msg = {"type": "END", "scores": leaderboard}
        send_json(p1, end_msg)
        send_json(p2, end_msg)
        print(f"[GAME] Session ended. Scores: {scores}")

    except Exception as e:
        # Catch-all so a crash in one session never brings down the server
        print(f"[ERROR] game_session crashed: {e}")

    finally:
        # Always close both sockets when the session is done
        try: p1.close()
        except: pass
        try: p2.close()
        except: pass


def _is_connected(conn):
    """
    Non-destructive liveness check: try sending 0 bytes.
    Returns False if the socket is no longer usable.
    """
    try:
        conn.send(b'')
        return True
    except OSError:
        return False


def _handle_early_disconnect(p1, p2, names):
    """
    One (or both) players disconnected during the name-collection phase.
    Notify whichever socket is still alive.
    """
    p1_ok = _is_connected(p1)
    p2_ok = _is_connected(p2)

    if p1_ok and not p2_ok:
        send_json(p1, {"type": "OPPONENT_LEFT",
                       "message": "Opponent disconnected before the game started.",
                       "your_score": 0})
    elif p2_ok and not p1_ok:
        send_json(p2, {"type": "OPPONENT_LEFT",
                       "message": "Opponent disconnected before the game started.",
                       "your_score": 0})

    try: p1.close()
    except: pass
    try: p2.close()
    except: pass


# --------------- Main server loop 

def start_server():
    """
    Binds the TCP socket, enters the accept loop, and populates the
    matchmaking queue.  When 2 players are queued they are popped and
    handed off to a new game_session thread.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR lets us restart the server immediately after stopping it
    # without waiting for the OS TIME_WAIT state to expire.
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[STARTING] Trivia server listening on {HOST}:{PORT}")

    try:
        while True:
            conn, addr = server.accept()
            print(f"[CONNECTED] {addr}")

            # Expect the initial CONNECT handshake before adding to queue
            msg = recv_json(conn)
            if msg and msg.get("type") == "CONNECT":
                with queue_lock:
                    matchmaking_queue.append(conn)
                    print(f"[QUEUE] {len(matchmaking_queue)} player(s) waiting")

                    if len(matchmaking_queue) >= 2:
                        p1 = matchmaking_queue.pop(0)
                        p2 = matchmaking_queue.pop(0)
                        print("[MATCH] Two players found – spawning game session")
                        # daemon=True means the thread won't block server shutdown
                        threading.Thread(
                            target=game_session,
                            args=(p1, p2),
                            daemon=True
                        ).start()
            else:
                # Reject clients that don't send the proper handshake
                conn.close()

    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server shutting down...")
    finally:
        server.close()


if __name__ == "__main__":
    start_server()
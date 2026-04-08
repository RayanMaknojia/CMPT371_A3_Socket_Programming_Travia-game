"""
CMPT 371 A3: Multiplayer Trivia Client
Architecture: JSON over TCP Protocol with tkinter GUI
Reference: Unicode/tkinter layout assistance from ChatGPT.

Critical design rule (tkinter + sockets):
  tkinter is SINGLE-THREADED – we must NEVER call recv() or any blocking
  network function on the main thread.  Doing so freezes the entire GUI.

All network I/O runs on a dedicated background ReceiverThread.
    It communicates results back to the main thread ONLY through
    root.after(0, callback), which is the only thread-safe tkinter call.
"""

import socket
import json
import threading
import tkinter as tk
from tkinter import font as tkfont

# -------------- Server address 
HOST = '127.0.0.1'   # Change to server's IP for LAN play
PORT = 5556

ANSWER_TIMEOUT_DISPLAY = 20   # Must match server-side ANSWER_TIMEOUT


# -------------- Network helpers 

def send_json(conn, data):
    """Serialize to JSON, append \n delimiter, and send."""
    msg = json.dumps(data) + "\n"
    conn.sendall(msg.encode('utf-8'))


def recv_json(conn):
    """
    Blocking receive – returns the first complete JSON message or None on
    disconnect.  Only calling this from a background thread, never from the
    main tkinter thread.
    """
    try:
        data = conn.recv(4096).decode('utf-8')
        if not data:
            return None
        return json.loads(data.strip().split("\n")[0])
    except (ConnectionResetError, OSError, json.JSONDecodeError):
        return None


# -------------- Main application class 

class TriviaClient:
    """
    Manages the tkinter GUI and all client-server communication.

    State machine (driven by server messages):
      CONNECT  →  NAME  →  waiting  →  START  →  [QUESTION → ROUND_RESULT] × N  →  END
                                                       ↓ (if opponent drops)
                                                   OPPONENT_LEFT
    """

    def __init__(self, root):
        self.root = root
        self.root.title("⚡ Trivia Duel")
        self.root.resizable(False, False)
        self._apply_theme()

        # -------------- Network state 
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.client.connect((HOST, PORT))
        send_json(self.client, {"type": "CONNECT"})

        # -------------- Game state 
        self.my_name   = ""
        self.opp_name  = ""
        self.time_left = ANSWER_TIMEOUT_DISPLAY
        self._timer_job = None    # tkinter after() handle so we can cancel it
        self._submitted = False   # Prevent double-submit within one question

        # -------------- Build UI 
        self.container = tk.Frame(root, bg=self.C["bg"])
        self.container.pack(fill="both", expand=True, padx=30, pady=30)

        self.show_name_screen()

        # -------------- Start the background receiver thread 
        self._receiver = threading.Thread(target=self._receiver_loop, daemon=True)
        self._receiver.start()

    # -------------- Theme / styling 

    def _apply_theme(self):
        """Define the colour palette used throughout the UI."""
        self.C = {
            "bg":      "#0d0d1a",   # Near-black background
            "panel":   "#161628",   # Slightly lighter panel
            "accent":  "#7c3aed",   # Purple accent
            "accent2": "#06b6d4",   # Cyan accent
            "correct": "#10b981",   # Green for correct
            "wrong":   "#ef4444",   # Red for wrong/time-up
            "text":    "#e2e8f0",   # Main text
            "muted":   "#64748b",   # Secondary/muted text
            "border":  "#2d2d4e",   # Border colour
        }
        self.root.configure(bg=self.C["bg"])

    def _btn(self, parent, text, command):
        """Reusable styled button factory."""
        return tk.Button(
            parent, text=text, command=command,
            bg=self.C["accent"], fg="white",
            activebackground=self.C["accent2"],
            activeforeground="white",
            font=("Courier New", 12, "bold"),
            relief="flat", bd=0,
            padx=20, pady=10, cursor="hand2"
        )

    def _label(self, parent, text, size=12, color=None, bold=False):
        """Reusable styled label factory."""
        weight = "bold" if bold else "normal"
        return tk.Label(
            parent, text=text,
            bg=self.C["bg"],
            fg=color or self.C["text"],
            font=("Courier New", size, weight),
            wraplength=440
        )

    # -------------- Screen helpers 

    def _clear(self):
        """Destroy all widgets in the container so the next screen can be drawn."""
        for w in self.container.winfo_children():
            w.destroy()

    # -------------- Screens (all called from main thread) 

    def show_name_screen(self):
        """Initial screen: ask the player for their display name."""
        self._clear()

        self._label(self.container, "⚡ TRIVIA DUEL", size=22, bold=True,
                    color=self.C["accent"]).pack(pady=(0, 6))
        self._label(self.container, "Enter your name to begin",
                    color=self.C["muted"]).pack(pady=(0, 20))

        self.name_entry = tk.Entry(
            self.container,
            font=("Courier New", 13),
            bg=self.C["panel"], fg=self.C["text"],
            insertbackground=self.C["accent2"],
            relief="flat", bd=0,
            justify="center", width=24
        )
        self.name_entry.pack(ipady=10, pady=(0, 16))
        self.name_entry.focus()
        # Allow pressing Enter as well as clicking Start
        self.name_entry.bind("<Return>", lambda e: self._submit_name())

        self._btn(self.container, "START  →", self._submit_name).pack()

    def _submit_name(self):
        """Send the player's name to the server, then show the waiting screen."""
        name = self.name_entry.get().strip()
        if not name:
            return
        self.my_name = name
        send_json(self.client, {"name": name})
        self.show_waiting_screen()

    def show_waiting_screen(self):
        """Shown after the player submits their name while waiting for an opponent."""
        self._clear()
        self._label(self.container, "Waiting for opponent…",
                    size=15, bold=True, color=self.C["accent2"]).pack(pady=(40, 10))
        self._label(self.container,
                    "The game will start automatically once a second player joins.",
                    color=self.C["muted"]).pack()

    def show_question_screen(self, q_text, progress):
        """Render the question, timer, answer entry, and submit button."""
        self._clear()
        self._submitted = False

        # Progress indicator (e.g. "... 3/10")
        self._label(self.container, f"Question {progress}",
                    size=10, color=self.C["muted"]).pack(anchor="w", pady=(0, 4))

        # Score display
        self._label(self.container,
                    f"You: {self._my_score}   {self.opp_name}: {self._opp_score}",
                    size=10, color=self.C["accent2"]).pack(anchor="e", pady=(0, 8))

        # Divider
        tk.Frame(self.container, bg=self.C["border"], height=1).pack(fill="x", pady=(0, 12))

        # Question text
        self._label(self.container, q_text, size=14, bold=True).pack(pady=(0, 20))

        # Countdown timer
        self.timer_var = tk.StringVar(value=f"⏱  {ANSWER_TIMEOUT_DISPLAY}s")
        self.timer_label = tk.Label(
            self.container, textvariable=self.timer_var,
            bg=self.C["bg"], fg=self.C["accent2"],
            font=("Courier New", 13, "bold")
        )
        self.timer_label.pack(pady=(0, 16))

        # Answer entry
        self.answer_entry = tk.Entry(
            self.container,
            font=("Courier New", 13),
            bg=self.C["panel"], fg=self.C["text"],
            insertbackground=self.C["accent2"],
            relief="flat", bd=0,
            justify="center", width=24
        )
        self.answer_entry.pack(ipady=10, pady=(0, 16))
        self.answer_entry.focus()
        self.answer_entry.bind("<Return>", lambda e: self._submit_answer())

        self.submit_btn = self._btn(self.container, "SUBMIT  →", self._submit_answer)
        self.submit_btn.pack()

        # Starting the visible countdown
        self.time_left = ANSWER_TIMEOUT_DISPLAY
        self._tick()

    def _tick(self):
        """Update the countdown label every second. Cancel when time hits 0."""
        if self.time_left < 0:
            return
        color = self.C["wrong"] if self.time_left <= 5 else self.C["accent2"]
        self.timer_var.set(f"⏱  {self.time_left}s")
        self.timer_label.config(fg=color)
        self.time_left -= 1
        # Schedule the next tick; keeping the handle so that we can cancel it on submit
        self._timer_job = self.root.after(1000, self._tick)

    def _stop_timer(self):
        """Cancel any pending timer tick."""
        if self._timer_job is not None:
            self.root.after_cancel(self._timer_job)
            self._timer_job = None

    def _submit_answer(self):
        """
        Send the typed answer to the server, stop the timer, and show a
        'waiting for opponent' message.  Guard against double-submission.
        """
        if self._submitted:
            return
        self._submitted = True

        self._stop_timer()
        ans = self.answer_entry.get().strip()
        send_json(self.client, {"answer": ans})

        # Disable input widgets to prevent edits after submission
        self.answer_entry.config(state="disabled")
        self.submit_btn.config(state="disabled")

        self._label(self.container,
                    "✓ Answer submitted!\nWaiting for opponent…",
                    color=self.C["muted"]).pack(pady=12)

    def show_round_result(self, you_result, opp_result, my_score, opp_score):
        """
        Display per-round feedback after both players have answered (or timed out).
        Stays visible until the server sends the next QUESTION (4-second server pause).
        Result strings from the server follow this format:
          "✓ Correct! (+1)"
          "✗ Wrong! (Answer: paris)"
          "✗ Time\'s up! (Answer: paris)"
        """
        self._clear()
        self._stop_timer()

        # -------------- prompt based on outcome 
        if "Correct" in you_result:
            headline       = "✓  Correct!"
            headline_color = self.C["correct"]
        elif "Time" in you_result:
            headline       = "⏱  Time\'s up!"
            headline_color = self.C["wrong"]
        else:
            headline       = "✗  Wrong!"
            headline_color = self.C["wrong"]

        self._label(self.container, headline,
                    size=20, bold=True, color=headline_color).pack(pady=(0, 6))

        # --------------  full result line 
        self._label(self.container, you_result,
                    size=12, color=headline_color, bold=True).pack(pady=(0, 16))

        # -------------- Divider 
        tk.Frame(self.container, bg=self.C["border"], height=1).pack(fill="x", pady=(0, 12))

        # -------------- Opponent result 
        opp_color = self.C["correct"] if "Correct" in opp_result else self.C["wrong"]
        self._label(self.container, f"{self.opp_name}:  {opp_result}",
                    color=opp_color).pack(pady=4)

        # -------------- Running score 
        tk.Frame(self.container, bg=self.C["border"], height=1).pack(fill="x", pady=12)
        self._label(self.container,
                    f"Score  —  You: {my_score}   {self.opp_name}: {opp_score}",
                    size=11, color=self.C["accent2"]).pack()

        self._label(self.container, "Next question coming up…",
                    color=self.C["muted"]).pack(pady=(12, 0))

        # a running copy for the question header
        self._my_score  = my_score
        self._opp_score = opp_score

    def show_end_screen(self, scores):
        """Final leaderboard screen."""
        self._clear()
        self._stop_timer()

        self._label(self.container, "🏆 GAME OVER",
                    size=20, bold=True, color=self.C["accent"]).pack(pady=(0, 20))

        for rank, (name, score) in enumerate(scores, start=1):
            medal = "🥇" if rank == 1 else "🥈"
            is_me = (name == self.my_name)
            color = self.C["accent2"] if is_me else self.C["text"]
            bold_flag = True if is_me else False
            self._label(self.container,
                        f"{medal}  {name}  —  {score} pts",
                        size=14, color=color, bold=bold_flag).pack(pady=6)

        tk.Frame(self.container, bg=self.C["border"], height=1).pack(fill="x", pady=16)
        self._btn(self.container, "Exit", self.root.quit).pack()

    def show_opponent_left(self, message, your_score):
        """Shown when the opponent disconnects mid-game."""
        self._clear()
        self._stop_timer()

        self._label(self.container, "😮 Opponent Disconnected",
                    size=16, bold=True, color=self.C["wrong"]).pack(pady=(0, 16))
        self._label(self.container, message,
                    color=self.C["text"]).pack(pady=(0, 12))
        self._label(self.container, f"Your final score: {your_score}",
                    size=14, color=self.C["accent2"], bold=True).pack(pady=(0, 20))
        self._btn(self.container, "Exit", self.root.quit).pack()

    # -------------- Background receiver thread 

    def _receiver_loop(self):
        """
        Runs on a daemon thread.  Continuously reads from the server socket
        and dispatches each message to the main thread via root.after(0, fn).

        """
        # Initialise running scores so the question header has something to show
        self._my_score  = 0
        self._opp_score = 0

        while True:
            msg = recv_json(self.client)

            if msg is None:
                # Server closed connection unexpectedly
                self.root.after(0, self._on_server_disconnect)
                break

            msg_type = msg.get("type")

            if msg_type == "NAME":
                # Server is ready for player(lets say p1) name – name was already sent in
                # _submit_name(), nothing more needed here.
                pass

            elif msg_type == "WAIT":
                # Still waiting for the second player – UI already shows this
                pass

            elif msg_type == "START":
                self.opp_name = msg.get("opponent", "Opponent")
                self.root.after(0, lambda: self._label(
                    self.container,
                    f"🎯 Match found! vs {self.opp_name}",
                    size=14, bold=True, color=self.C["correct"]
                ).pack(pady=10))

            elif msg_type == "QUESTION":
                q    = msg["q"]
                prog = msg["progress"]
                # Schedule the screen transition on the main thread
                self.root.after(0, lambda q=q, p=prog: self.show_question_screen(q, p))

            elif msg_type == "ROUND_RESULT":
                you  = msg["you"]
                opp  = msg["opponent"]
                ms   = msg.get("your_score", self._my_score)
                os_  = msg.get("opponent_score", self._opp_score)
                self.root.after(0, lambda y=you, o=opp, m=ms, x=os_:
                                self.show_round_result(y, o, m, x))

            elif msg_type == "END":
                scores = msg["scores"]
                self.root.after(0, lambda s=scores: self.show_end_screen(s))
                break   # No more messages expected

            elif msg_type == "OPPONENT_LEFT":
                message    = msg.get("message", "Opponent disconnected.")
                your_score = msg.get("your_score", self._my_score)
                self.root.after(0, lambda m=message, s=your_score:
                                self.show_opponent_left(m, s))
                break

    def _on_server_disconnect(self):
        """Called on the main thread if the server closes unexpectedly."""
        self._clear()
        self._label(self.container,
                    "⚠ Connection to server lost.",
                    size=14, color=self.C["wrong"], bold=True).pack(pady=40)
        self._btn(self.container, "Exit", self.root.quit).pack()


# -------------- Entry point 

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("500x480")
    app = TriviaClient(root)
    root.mainloop()
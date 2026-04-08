# ⚡ Multiplayer Trivia Duel (CMPT 371)

## **Group Members**

| Name | Student ID | Email |
| :---- | :---- | :---- |
| Rayan Maknojia | 301467805 | rma120@sfu.ca |
| Riya Maknojia | 301563544 | rma124@sfu.ca |

## 📌 Overview

This project is a real-time multiplayer trivia game built using Python sockets and a tkinter GUI.
It follows a client-server architecture where two players are matched through a matchmaking queue and compete by answering questions simultaneously.

The game ensures synchronized gameplay using a JSON-based protocol and multithreading to handle concurrency.


## 🚀 Features

* Real-time multiplayer gameplay
* Matchmaking queue (game starts when 2 players join)
* Synchronized questions and results for both players
* Countdown timer (20 seconds per question)
* Score tracking and leaderboard
* GUI built using tkinter with modern styling
* JSON-based communication protocol
* Multithreaded server (1 thread per game session)



## 🎥 Video Demo
<span style="color: purple;"></span>  
A 2 minute demonstration of the multiplayer trivia game is provided below.
[**▶️ Watch Project Demo on YouTube**](https://youtu.be/xBg7UqnZEZQ)



## 🧠 Architecture

### Client-Server Model

* Server handles matchmaking and game sessions
* Each game session runs in its own thread
* Clients communicate using TCP sockets

### Protocol

All communication uses JSON messages with a `type` field:

Examples:

```
{ "type": "CONNECT" }
{ "type": "QUESTION", "q": "...", "progress": "3/10" }
{ "type": "ROUND_RESULT", "you": "...", "opponent": "..." }
```

### Message Boundary

Messages are delimited using `\n` to handle TCP stream parsing.


## ⚙️ Concurrency Model

### Server:

* 1 main thread → accepts connections
* 1 thread per game session
* 2 threads per question → collect answers concurrently

### Client:

* 1 main thread → tkinter GUI
* 1 background thread → handles server messages

👉 GUI is never blocked by network operations (uses `root.after()`)



## 🕹️ Gameplay Flow

1. Player enters name
2. Waits in matchmaking queue
3. Game starts when 2 players join
4. Both players receive the same question
5. Players answer within 20 seconds
6. Results are shown simultaneously
7. Repeat for all questions
8. Final leaderboard displayed



## ▶️ How to Run on a single device or 🌐 Multiplayer Setup (LAN)

1. Find server IP:   Type the following command in the terminal of the device where you want to run the server
```
ipconfig
```
  find the ipv4 address and copy the ipaddress: eg, It will look something like this: 127.0.0.1


2. Replace in `client.py`: replace the HOST address in client with the one you copied

```
HOST = 'replace_here'
```

3. Ensure both devices are on same network
   
4.  Connect Player 1 

Open a **new** terminal window (keep the server running). Run the client script to start the first client.  
```
python client.py  
# Console output: "Connected. Waiting for opponent..."
```

5. Connect Player 2 

Open a **third** terminal window if 2 players on same device or open a terminal on the 2nd device( make sure you have client.py file in this device as well). Run the client script  to start the second client.  
```
python client.py  
# Console output: "Connected. Waiting for opponent..."
# Console output: "Match found!"
```

⚠️ Limitations
* No Persistent User Accounts
  * Players are identified only by a temporary name during each session. No data (scores or history) is saved after the game ends.  
* No Reconnection Support
  * If a player disconnects, the game session immediately ends and cannot be resumed. The remaining player is declared the winner.
* Thread-Based Scalability Constraints
  * The server uses a thread-per-session model. While effective for small-scale use, it may not scale efficiently with a large number of concurrent players.
* Basic GUI (tkinter Limitations)
  * The interface is built with tkinter, which limits advanced UI features such as animations, responsiveness, and modern design compared to frameworks like PyQt or web-based UIs.
* Unencrypted Communication (Plain TCP)
  * All data is transmitted over raw TCP without encryption, making it unsuitable for secure or public network environments.
* Firewall / Network Restrictions
  * Local firewall settings (e.g., Windows Defender Firewall) may block socket connections, preventing clients from connecting unless manually configured.



## 🔧 Extra possible features 

* Add user accounts and login system
* Web-based version so that it can run over the internet
* Database for leaderboard persistence
* Improved matchmaking system
* Chat functionality during gameplay
* Multiple choice questions can be added
* images or GIFs can be supported for questions




## ✅ Academic Integrity & References
<span style="color: purple;">*** all references used and help i got. ***</span>

* Code Origin:  
  * The socket coding, multithreading and TCP code was all written with the help of tutorials listed in the course details, also a little inspiration from the TA source code plus prior knowledge of the members of the team.
* GenAI Usage:
  * ChatGPT was used to assist in the logic and creation of GUI(Tkinter), styling and colorpallet, and complete frontend was done with the assistance of ChatGPT.  
  * ChatGPT was used to help in `README.md` Structuring, Everything was typed in by both members of the team.  
* References: \
  * [Python TCP/IP socket programming](https://www.youtube.com/playlist?list=PLhTjy8cBISErYuLZUvVOYsR1giva2payF)  
  * [TA cmpt 371 tutorial, Multiplayer tictactoe](https://www.youtube.com/playlist?list=PL-8C2cUhmkO1yWLTCiqf4mFXId73phvdx)
  * [Python UDP network programming, listening, binding. etc](https://www.youtube.com/watch?v=oEOiBt6mD6Y)  

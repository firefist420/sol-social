import streamlit as st
import requests
import sqlite3
import base64
import json
import os
from dotenv import load_dotenv

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

if "user_id" not in st.session_state:
    st.session_state.update({
        "user_id": None,
        "wallet_connected": False,
        "wallet_address": "",
        "signed_message": [],
        "message": "",
        "posts": []
    })

def init_db():
    with sqlite3.connect("solsocial.db") as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                wallet_address TEXT PRIMARY KEY,
                username TEXT,
                signed_message TEXT,
                message TEXT
            );
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                author TEXT,
                wallet_address TEXT,
                likes INTEGER DEFAULT 0,
                liked_by TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

init_db()

def set_background(image_path):
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    st.markdown(f"""
        <style>
        .stApp {{
            background-image: url(data:image/jpeg;base64,{encoded});
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
        """, unsafe_allow_html=True)

set_background("assets/background.jpg.jpeg")

def wallet_connector_script():
    return """
    <script>
    async function connectWallet() {
        if (!window.solana?.isPhantom) return;
        try {
            const response = await window.solana.connect();
            const publicKey = response.publicKey.toString();
            const message = "Welcome to SolSocial!";
            const signedMessage = await window.solana.signMessage(new TextEncoder().encode(message));
            window.parent.postMessage({
                type: "walletConnected",
                publicKey: publicKey,
                signedMessage: Array.from(signedMessage.signature),
                message: message
            }, "*");
        } catch (error) {
            console.error("Connection failed:", error);
        }
    }
    document.getElementById("connect-button").addEventListener("click", connectWallet);
    </script>
    """

def connect_wallet_button():
    st.markdown("""
    <style>
    .connect-button {
        background-color: purple;
        color: white;
        border: none;
        padding: 12px 24px;
        font-size: 16px;
        cursor: pointer;
        border-radius: 25px;
        position: fixed;
        top: 20px;
        left: 20px;
        z-index: 1;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    .connect-button:hover {
        background-color: #6a0dad;
        transform: scale(1.05);
    }
    .overlay {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0,0,0,0.5);
    }
    .signup-box {
        background-color: rgba(255,255,255,0.9);
        padding: 2rem;
        border-radius: 15px;
        width: 50%;
        margin: 0 auto;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
    }
    </style>
    <div class="overlay"></div>
    <button id="connect-button" class="connect-button">
        <img src="https://phantom.app/favicon.ico" width="20" style="vertical-align:middle; margin-right:8px;">
        Connect Wallet
    </button>
    """, unsafe_allow_html=True)
    st.markdown(wallet_connector_script(), unsafe_allow_html=True)

def signup_form():
    with st.container():
        st.markdown('<div class="signup-box">', unsafe_allow_html=True)
        username = st.text_input("Choose username:")
        if st.button("Sign Up"):
            with sqlite3.connect("solsocial.db") as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
                    (st.session_state["wallet_address"], username, 
                     json.dumps(st.session_state["signed_message"]), 
                     st.session_state["message"])
                )
            st.session_state["user_id"] = username or st.session_state["wallet_address"]
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

def post_feed():
    st.title("Home")
    st.write(f"Welcome, {st.session_state['user_id']}")
    
    with st.form("post_form"):
        post_content = st.text_area("What's on your mind?")
        if st.form_submit_button("Post") and post_content:
            try:
                requests.post(
                    f"{BACKEND_URL}/posts",
                    json={
                        "content": post_content,
                        "author": st.session_state['user_id'],
                        "wallet_address": st.session_state['wallet_address']
                    }
                )
                st.rerun()
            except Exception as e:
                st.error(f"Posting failed: {str(e)}")

    try:
        posts = requests.get(f"{BACKEND_URL}/posts").json()
        for post in posts:
            with st.container(border=True):
                st.write(f"**{post['author']}**")
                st.write(post['content'])
                liked = st.session_state['wallet_address'] in post.get('liked_by', [])
                if st.button(f"{'❤️' if liked else '♡'} {post.get('likes',0)}", key=f"like_{post['id']}"):
                    requests.post(
                        f"{BACKEND_URL}/posts/{post['id']}/like",
                        json={"wallet_address": st.session_state['wallet_address']}
                    )
                    st.rerun()
    except Exception:
        st.error("Couldn't load posts")

if st.session_state["user_id"]:
    post_feed()
else:
    connect_wallet_button()
    if st.session_state.get("wallet_connected"):
        try:
            response = requests.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": st.session_state["wallet_address"],
                    "signed_message": st.session_state["signed_message"],
                    "message": st.session_state["message"]
                }
            )
            if response.status_code == 200:
                signup_form()
        except Exception as e:
            st.error(f"Authentication failed: {str(e)}")

st.markdown("""
<script>
window.addEventListener("message", (e) => {
    if (e.data.type === "walletConnected") {
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: {
                wallet_connected: true,
                wallet_address: e.data.publicKey,
                signed_message: e.data.signedMessage,
                message: e.data.message
            }
        }, "*");
    }
});
</script>
""", unsafe_allow_html=True)
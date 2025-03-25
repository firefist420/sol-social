import streamlit as st
from solana.rpc.api import Client
from dotenv import load_dotenv
import os
import requests
import sqlite3
import base64
import json

load_dotenv()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
client = Client(SOLANA_RPC_URL)
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

def add_bg_from_local(image_file):
    with open(image_file, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read())
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: url(data:image/jpeg;base64,{encoded_string.decode()});
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )

add_bg_from_local(r'C:\Users\17327\Desktop\sol_social\assets\background.jpg.jpeg')

session_defaults = {
    "user_id": None,
    "wallet_connected": False,
    "wallet_address": "",
    "signed_message": [],
    "message": "",
    "posts": []
}
for key, val in session_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val

def init_db():
    with sqlite3.connect("solsocial.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                wallet_address TEXT PRIMARY KEY,
                username TEXT,
                signed_message TEXT,
                message TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT,
                author TEXT,
                wallet_address TEXT,
                likes INTEGER DEFAULT 0,
                liked_by TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

init_db()

def phantom_login():
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

def home_screen():
    st.title("Home")
    st.write(f"Welcome, {st.session_state['user_id']}")
    
    with st.form("post_form"):
        post_content = st.text_area("What's on your mind?")
        if st.form_submit_button("Post") and post_content:
            try:
                response = requests.post(
                    f"{BACKEND_URL}/posts",
                    json={
                        "content": post_content,
                        "author": st.session_state['user_id'],
                        "wallet_address": st.session_state['wallet_address']
                    }
                )
                if response.status_code == 200:
                    st.rerun()
            except Exception as e:
                st.error(f"Posting failed: {str(e)}")

    try:
        response = requests.get(f"{BACKEND_URL}/posts")
        if response.status_code == 200:
            for post in response.json():
                liked_by = post.get('liked_by', [])
                with st.container(border=True):
                    st.write(f"**{post['author']}**")
                    st.write(post['content'])
                    like_status = "❤️" if st.session_state['wallet_address'] in liked_by else "♡"
                    if st.button(f"{like_status} {post.get('likes',0)}", key=f"like_{post['id']}"):
                        requests.post(
                            f"{BACKEND_URL}/posts/{post['id']}/like",
                            json={"wallet_address": st.session_state['wallet_address']}
                        )
                        st.rerun()
    except Exception as e:
        st.error(f"Couldn't load posts: {str(e)}")

if st.session_state["user_id"]:
    home_screen()
else:
    st.markdown(f"""
    <style>
    .connect-button {{
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
    }}
    .connect-button:hover {{
        background-color: #6a0dad;
        transform: scale(1.05);
    }}
    .overlay {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-color: rgba(0,0,0,0.5);
    }}
    </style>
    <div class="overlay"></div>
    <button id="connect-button" class="connect-button">
        <img src="https://phantom.app/favicon.ico" width="20" style="vertical-align:middle; margin-right:8px;">
        Connect Wallet
    </button>
    """, unsafe_allow_html=True)
    st.markdown(phantom_login(), unsafe_allow_html=True)

    if st.session_state.get("wallet_connected"):
        try:
            auth_response = requests.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": st.session_state["wallet_address"],
                    "signed_message": st.session_state["signed_message"],
                    "message": st.session_state["message"]
                }
            )
            if auth_response.status_code == 200:
                with st.container():
                    st.markdown("""
                    <style>
                    .signup-box {
                        background-color: rgba(255,255,255,0.9);
                        padding: 2rem;
                        border-radius: 15px;
                        width: 50%;
                        margin: 0 auto;
                        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                    }
                    </style>
                    <div class="signup-box">
                    """, unsafe_allow_html=True)
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
                    st.markdown("</div>", unsafe_allow_html=True)
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
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
BACKEND_URL = os.getenv("BACKEND_URL", "https://your-render-service.onrender.com")

session_defaults = {
    "user_id": None,
    "wallet_connected": False,
    "wallet_address": "",
    "signed_message": "",
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

init_db()

def phantom_login():
    return """
    <script>
    async function connectWallet() {
        if (!window.solana?.isPhantom) {
            alert("Please install Phantom Wallet!");
            return;
        }
        try {
            const response = await window.solana.connect();
            const publicKey = response.publicKey.toString();
            const message = "Welcome to SolSocial!";
            const encodedMessage = new TextEncoder().encode(message);
            const signedMessage = await window.solana.signMessage(encodedMessage);
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
    st.write(f"Wallet: {st.session_state['wallet_address'][:6]}...{st.session_state['wallet_address'][-4:]}")
    
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
                    st.session_state["posts"].append(response.json())
                    st.rerun()
            except Exception:
                st.error("Posting failed")

    st.header("Feed")
    try:
        response = requests.get(f"{BACKEND_URL}/posts")
        if response.status_code == 200:
            for post in response.json():
                with st.container(border=True):
                    st.write(f"**{post['author']}**")
                    st.write(post['content'])
                    if st.button(f"?? {post.get('likes',0)}", key=f"like_{post['id']}"):
                        requests.post(f"{BACKEND_URL}/posts/{post['id']}/like", 
                                     json={"wallet_address": st.session_state['wallet_address']})
                        st.rerun()
    except Exception:
        st.error("Couldn't load posts")

def get_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

background_image_base64 = get_image_base64("assets/background.jpg")

if st.session_state["user_id"]:
    home_screen()
else:
    st.markdown(f"""
    <style>
    .connect-button {{
        background-color: purple;
        color: white;
        border: none;
        padding: 8px 16px;
        font-size: 14px;
        cursor: pointer;
        border-radius: 5px;
        position: absolute;
        top: 30px;
        right: 30px;
        z-index: 1;
    }}
    .solana-background {{
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background-image: url('data:image/jpg;base64,{background_image_base64}');
        background-size: cover;
    }}
    </style>
    <div class="solana-background">
        <button id="connect-button" class="connect-button">
            <img src="https://phantom.app/favicon.ico" width="16" style="vertical-align:middle; margin-right:4px;">
            Connect Wallet
        </button>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(phantom_login(), unsafe_allow_html=True)

    if st.session_state.get("wallet_connected"):
        wallet_address = st.session_state["wallet_address"]
        try:
            auth_response = requests.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": wallet_address,
                    "signed_message": st.session_state["signed_message"],
                    "message": st.session_state["message"]
                }
            )
            if auth_response.status_code == 200:
                username = st.text_input("Choose username:")
                if st.button("Sign Up"):
                    with sqlite3.connect("solsocial.db") as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?)",
                            (wallet_address, username, json.dumps(st.session_state["signed_message"]), st.session_state["message"])
                        )
                    st.session_state["user_id"] = username or wallet_address
                    st.rerun()
        except Exception:
            st.error("Authentication failed")

st.markdown("""
<script>
window.addEventListener("message", (e) => {
    if (e.data.type === "walletConnected") {
        const { publicKey, signedMessage, message } = e.data;
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: {
                wallet_connected: true,
                wallet_address: publicKey,
                signed_message: signedMessage,
                message: message
            }
        }, "*");
    }
});
</script>
""", unsafe_allow_html=True)
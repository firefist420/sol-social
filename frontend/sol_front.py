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

if "user_id" not in st.session_state:
    st.session_state["user_id"] = None
if "wallet_connected" not in st.session_state:
    st.session_state["wallet_connected"] = False
if "wallet_address" not in st.session_state:
    st.session_state["wallet_address"] = ""
if "signed_message" not in st.session_state:
    st.session_state["signed_message"] = ""
if "message" not in st.session_state:
    st.session_state["message"] = ""
if "posts" not in st.session_state:
    st.session_state["posts"] = []

def init_db():
    conn = sqlite3.connect("solsocial.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            wallet_address TEXT PRIMARY KEY,
            username TEXT,
            signed_message TEXT,
            message TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

def phantom_login():
    return """
        <script>
        async function connectWallet() {
            if (!window.solana || !window.solana.isPhantom) {
                alert("Phantom Wallet not found! Please install the Phantom Wallet extension.");
                return;
            }
            const phantom = window.solana;
            try {
                const response = await phantom.connect();
                const publicKey = response.publicKey.toString();
                const message = "Welcome to SolSocial! Please sign this message to verify your wallet.";
                const encodedMessage = new TextEncoder().encode(message);
                const signedMessage = await phantom.signMessage(encodedMessage, "utf8");
                window.parent.postMessage({
                    type: "walletConnected",
                    publicKey: publicKey,
                    signedMessage: Array.from(signedMessage.signature),
                    message: message
                }, "*");
            } catch (error) {
                console.error("Wallet connection failed:", error);
                alert("Wallet connection failed. Please try again.");
            }
        }
        document.getElementById("connect-button").addEventListener("click", connectWallet);
        </script>
    """

def home_screen():
    st.title("Home")
    st.write(f"Welcome, {st.session_state['user_id']}")
    st.write(f"Wallet: {st.session_state['wallet_address'][:6]}...{st.session_state['wallet_address'][-4:]}")
    
    st.header("Create Post")
    post_content = st.text_area("What's on your mind?", key="post_content")
    if st.button("Post"):
        if post_content:
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
                    st.success("Post created!")
                else:
                    st.error("Failed to create post")
            except Exception as e:
                st.error(f"Error: {e}")
    
    st.header("Feed")
    try:
        response = requests.get(f"{BACKEND_URL}/posts")
        if response.status_code == 200:
            posts = response.json()
            for post in posts:
                with st.container():
                    st.write(f"**{post['author']}**")
                    st.write(post['content'])
                    if st.button(f"?? {post.get('likes', 0)}", key=f"like_{post['id']}"):
                        like_response = requests.post(
                            f"{BACKEND_URL}/posts/{post['id']}/like",
                            json={"wallet_address": st.session_state['wallet_address']}
                        )
                        if like_response.status_code == 200:
                            st.experimental_rerun()
    except Exception as e:
        st.error(f"Error loading posts: {e}")

def get_image_base64(path):
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

background_image_path = "assets/background.jpg"
background_image_base64 = get_image_base64(background_image_path)

if st.session_state["user_id"]:
    home_screen()
else:
    st.markdown(f"""
        <style>
        .connect-button {{
            background-color: purple;
            color: white;
            border: none;
            padding: 10px 20px;
            font-size: 16px;
            cursor: pointer;
            border-radius: 5px;
            position: absolute;
            top: 20px;
            right: 20px;
            z-index: 1;
        }}
        .connect-button:hover {{
            background-color: darkviolet;
        }}
        .solana-background {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: url('data:image/jpg;base64,{background_image_base64}');
            background-size: cover;
            background-position: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            color: white;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }}
        </style>
        <div class="solana-background">
            <button id="connect-button" class="connect-button">
                <img src="https://phantom.app/favicon.ico" alt="Phantom Logo" width="20" style="vertical-align: middle; margin-right: 5px;">
                Connect Phantom Wallet
            </button>
        </div>
    """, unsafe_allow_html=True)

    st.markdown(phantom_login(), unsafe_allow_html=True)

    if st.session_state.get("wallet_connected"):
        wallet_address = st.session_state["wallet_address"]
        st.write(f"Connected Wallet: {wallet_address[:6]}...{wallet_address[-4:]}")
        message = st.session_state["message"]
        signed_message = st.session_state["signed_message"]

        try:
            auth_response = requests.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": wallet_address,
                    "signed_message": signed_message,
                    "message": message
                }
            )
            
            if auth_response.status_code == 200:
                data = auth_response.json()
                username = st.text_input("Choose a username (optional):")
                if st.button("Complete Sign Up"):
                    conn = sqlite3.connect("solsocial.db")
                    c = conn.cursor()
                    c.execute(
                        "INSERT OR REPLACE INTO users (wallet_address, username, signed_message, message) VALUES (?, ?, ?, ?)",
                        (wallet_address, username, json.dumps(signed_message), message)
                    conn.commit()
                    conn.close()
                    st.session_state["user_id"] = username or wallet_address
                    st.experimental_rerun()
            else:
                st.error("Wallet verification failed")
        except Exception as e:
            st.error(f"Authentication error: {e}")

st.markdown("""
    <script>
    window.addEventListener("message", (event) => {
        if (event.data.type === "walletConnected") {
            const { publicKey, signedMessage, message } = event.data;
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
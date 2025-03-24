import streamlit as st
from solana.rpc.api import Client
from dotenv import load_dotenv
import os
import requests
import sqlite3
import base64

load_dotenv()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL")
client = Client(SOLANA_RPC_URL)

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
    st.write(f"Welcome, User: {st.session_state['user_id']}")
    st.write(f"Wallet Address: {st.session_state['wallet_address']}")
    st.header("Create a Post")
    post_content = st.text_area("What's on your mind?")
    if st.button("Post"):
        if post_content:
            new_post = {
                "id": len(st.session_state["posts"]) + 1,
                "content": post_content,
                "author": st.session_state["user_id"],
                "likes": 0
            }
            st.session_state["posts"].append(new_post)
            st.success("Post created!")
    st.header("Feed")
    for post in st.session_state["posts"]:
        st.write(f"**{post['author']}**: {post['content']}")
        st.write(f"Likes: {post['likes']}")
        if st.button(f"Like {post['id']}"):
            post["likes"] += 1
            st.experimental_rerun()

def get_image_base64(path):
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

background_image_path = "C:/Users/17327/Desktop/sol_social/assets/background.jpg.jpeg"
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
                <img src="https://th.bing.com/th/id/OIP.PkbqSXzG2ppbbP3dXWOM8AAAAA?rs=1&pid=ImgDetMain" alt="Phantom Logo" width="20" style="vertical-align: middle; margin-right: 5px;">
                Connect Phantom Wallet
            </button>
        </div>
    """, unsafe_allow_html=True)

    st.markdown(phantom_login(), unsafe_allow_html=True)

    if st.session_state.get("wallet_connected"):
        wallet_address = st.session_state["wallet_address"]
        st.write(f"Connected Wallet: {wallet_address}")
        message = st.session_state["message"]
        signed_message = st.session_state["signed_message"]

        conn = sqlite3.connect("solsocial.db")
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE wallet_address = ?", (wallet_address,))
        user = c.fetchone()
        conn.close()

        if user:
            st.session_state["user_id"] = user[1] if user[1] else wallet_address
            st.experimental_rerun()
        else:
            username = st.text_input("Choose a username (optional):")
            if st.button("Sign Up"):
                auth_url = "http://127.0.0.1:8000/auth/wallet"
                payload = {
                    "wallet_address": wallet_address,
                    "signed_message": signed_message,
                    "message": message,
                }
                try:
                    response = requests.post(auth_url, json=payload)
                    response.raise_for_status()
                    if response.json().get("success"):
                        conn = sqlite3.connect("solsocial.db")
                        c = conn.cursor()
                        c.execute("INSERT INTO users (wallet_address, username, signed_message, message) VALUES (?, ?, ?, ?)",
                                  (wallet_address, username, str(signed_message), message))
                        conn.commit()
                        conn.close()

                        st.session_state["user_id"] = username if username else wallet_address
                        st.session_state["wallet_connected"] = True
                        st.experimental_rerun()
                    else:
                        st.error("Wallet verification failed. Please check your wallet and try again.")
                except requests.exceptions.RequestException as e:
                    st.error(f"An error occurred: {e}")

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
# -*- coding: utf-8 -*-

import streamlit as st
import httpx
import sqlite3
import json
import os
from dotenv import load_dotenv
import streamlit.web.bootstrap

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

if "user_data" not in st.session_state:
    st.session_state.update({
        "user_data": {
            "user_id": None,
            "wallet_address": "",
            "auth_token": None
        },
        "wallet_connected": False
    })

def init_db():
    with sqlite3.connect("solsocial.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                wallet_address TEXT PRIMARY KEY,
                username TEXT,
                auth_token TEXT
            )
        """)

init_db()

def set_background():
    st.markdown("""
    <style>
    .stApp {
        background-image: url('https://i.ibb.co/YBngK5s6/background-jpg.jpg');
        background-size: cover;
        background-position: center;
        background-repeat: no-repeat;
        background-attachment: fixed;
    }
    </style>
    """, unsafe_allow_html=True)

set_background()

def wallet_connector():
    st.markdown("""
    <script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
    <script>
    async function connectWallet() {
        if (!window.solana?.isPhantom) return alert("Phantom not found");
        try {
            const response = await window.solana.connect();
            const publicKey = response.publicKey.toString();
            const message = `SolSocial Auth ${Date.now()}`;
            const signedMessage = await window.solana.signMessage(new TextEncoder().encode(message));
            window.parent.postMessage({
                type: "walletConnected",
                publicKey: publicKey,
                signedMessage: Array.from(signedMessage.signature),
                message: message
            }, "*");
        } catch (error) {
            console.error(error);
        }
    }
    document.getElementById("connect-button").addEventListener("click", connectWallet);
    </script>
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
    </style>
    <button id="connect-button" class="connect-button">
        <img src="https://phantom.app/favicon.ico" width="20" style="vertical-align:middle; margin-right:8px;">
        Connect Wallet
    </button>
    """, unsafe_allow_html=True)

async def auth_wallet(wallet, sig, msg):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": wallet,
                    "signed_message": sig,
                    "message": msg
                }
            )
            if r.status_code == 200:
                data = r.json()
                st.session_state.user_data = {
                    "user_id": data["user_id"],
                    "wallet_address": wallet,
                    "auth_token": data["auth_token"]
                }
                with sqlite3.connect("solsocial.db") as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
                        (wallet, data["user_id"], data["auth_token"])
                    )
                return True
    except Exception:
        return False

def signup_form():
    username = st.text_input("Choose username:")
    if st.button("Sign Up"):
        st.session_state.user_data["user_id"] = username or st.session_state.user_data["wallet_address"]
        st.rerun()

async def fetch_posts():
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{BACKEND_URL}/posts")
            return r.json() if r.status_code == 200 else []
    except Exception:
        return []

async def submit_post(content, author):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/posts",
                json={
                    "content": content,
                    "author": author,
                    "wallet_address": st.session_state.user_data["wallet_address"]
                },
                headers={"Authorization": f"Bearer {st.session_state.user_data['auth_token']}"}
            )
            return r.status_code == 200
    except Exception:
        return False

async def handle_like(post_id):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/posts/{post_id}/like",
                headers={"Authorization": f"Bearer {st.session_state.user_data['auth_token']}"}
            )
            return r.status_code == 200
    except Exception:
        return False

async def render_feed():
    st.title("Home")
    st.write(f"Welcome, {st.session_state.user_data['user_id']}")
    
    with st.form("post_form"):
        content = st.text_area("What's on your mind?")
        if st.form_submit_button("Post") and content:
            if await submit_post(content, st.session_state.user_data["user_id"]):
                st.rerun()
            else:
                st.error("Posting failed")

    posts = await fetch_posts()
    for post in posts:
        with st.container(border=True):
            st.write(f"**{post['author']}**")
            st.write(post['content'])
            liked = st.session_state.user_data["wallet_address"] in post.get('liked_by', [])
            if st.button(f"{'❤️' if liked else '♡'} {post.get('likes',0)}", key=f"like_{post['id']}"):
                if await handle_like(post['id']):
                    st.rerun()
                else:
                    st.error("Like failed")

if st.session_state.user_data["user_id"]:
    st.sidebar.write(f"User: {st.session_state.user_data['user_id']}")
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()
    st.experimental_rerun(render_feed)()
else:
    wallet_connector()
    if st.session_state.get("wallet_connected"):
        if st.session_state.user_data["auth_token"] is None:
            if st.experimental_rerun(auth_wallet)(
                st.session_state["wallet_address"],
                st.session_state["signed_message"],
                st.session_state["message"]
            ):
                signup_form()
            else:
                st.error("Auth failed")

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

if __name__ == "__main__":
    streamlit.web.bootstrap.run("sol_front.py", "", [], {})
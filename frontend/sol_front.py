import streamlit as st
import httpx
import sqlite3
import os
from dotenv import load_dotenv
import streamlit.web.bootstrap
import streamlit.components.v1 as components

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL", "https://your-render-app.onrender.com")
HCAPTCHA_SITEKEY = os.getenv("HCAPTCHA_SITEKEY")

st.set_page_config(page_title="SolSocial", layout="wide")

if "user_data" not in st.session_state:
    st.session_state.update({
        "user_data": {
            "user_id": None,
            "wallet_address": "",
            "auth_token": None
        },
        "wallet_connected": False,
        "hcaptcha_token": None,
        "backend_checked": False
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
    }
    </style>
    """, unsafe_allow_html=True)

set_background()

async def check_backend():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/")
            return response.status_code == 200
    except Exception:
        return False

def show_captcha():
    components.html(f"""
    <script src="https://js.hcaptcha.com/1/api.js" async defer></script>
    <div class="h-captcha" data-sitekey="{HCAPTCHA_SITEKEY}" data-callback="onCaptchaSubmit"></div>
    <script>
    function onCaptchaSubmit(token) {
        window.parent.postMessage({
            type: "hcaptcha_verified",
            token: token
        }, "*");
    }
    </script>
    """, height=100)

def wallet_connector():
    if not st.session_state.get("hcaptcha_token"):
        show_captcha()
        return
    
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
    <button id="connect-button" class="connect-button">
        <img src="https://phantom.app/favicon.ico" width="20">
        Connect Wallet
    </button>
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
    }
    </style>
    """, unsafe_allow_html=True)

async def auth_wallet(wallet, sig, msg, hcaptcha_token):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BACKEND_URL}/auth/wallet",
                data={
                    "wallet_address": wallet,
                    "signed_message": sig,
                    "message": msg,
                    "hcaptcha_token": hcaptcha_token
                }
            )
            if r.status_code == 200:
                data = r.json()
                st.session_state.user_data = {
                    "user_id": data.get("user_id", wallet),
                    "wallet_address": wallet,
                    "auth_token": data.get("auth_token")
                }
                with sqlite3.connect("solsocial.db") as conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO users VALUES (?, ?, ?)",
                        (wallet, st.session_state.user_data["user_id"], st.session_state.user_data["auth_token"])
                    )
                return True
    except Exception:
        return False

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

async def render_feed():
    st.title("Home")
    st.write(f"Welcome, {st.session_state.user_data['user_id']}")
    
    with st.form("post_form"):
        content = st.text_area("What's on your mind?")
        if st.form_submit_button("Post") and content:
            if await submit_post(content, st.session_state.user_data["user_id"]):
                st.rerun()

    posts = await fetch_posts()
    for post in posts:
        with st.container(border=True):
            st.write(f"**{post['author']}**")
            st.write(post['content'])

if not st.session_state.get('backend_checked'):
    if not await check_backend():
        st.error("Backend service unavailable")
        st.stop()
    st.session_state.backend_checked = True

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
                st.session_state["message"],
                st.session_state["hcaptcha_token"]
            ):
                st.rerun()

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
    if (e.data.type === "hcaptcha_verified") {
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: {
                hcaptcha_token: e.data.token
            }
        }, "*");
    }
});
</script>
""", unsafe_allow_html=True)

if __name__ == "__main__":
    streamlit.web.bootstrap.run("sol_front.py", "", [], {})
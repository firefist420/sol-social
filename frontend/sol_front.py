import streamlit as st
import httpx
import os
import asyncio
from dotenv import load_dotenv
import streamlit.components.v1 as components
from datetime import datetime
from typing import Optional, Dict, Any

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
HCAPTCHA_SITEKEY = os.getenv("HCAPTCHA_SITEKEY", "")
PAGE_TITLE = "SolSocial"

st.set_page_config(page_title=PAGE_TITLE, layout="wide")

def init_session():
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

def clear_session():
    keys = list(st.session_state.keys())
    for key in keys:
        del st.session_state[key]
    init_session()

init_session()

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
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{BACKEND_URL}/health")
            return response.status_code == 200
    except Exception as e:
        st.error(f"Backend connection error: {str(e)}")
        return False

def show_captcha():
    components.html(f"""
    <script src="https://js.hcaptcha.com/1/api.js" async defer></script>
    <div class="h-captcha" data-sitekey="{HCAPTCHA_SITEKEY}" data-callback="onCaptchaSubmit"></div>
    <script>
    function onCaptchaSubmit(token) {{
        window.parent.postMessage({{
            type: "hcaptcha_verified",
            token: token
        }}, "*");
    }}
    </script>
    """, height=100)

def wallet_connector():
    components.html(f"""
    <script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
    <script>
    async function connectWallet() {{
        if (!window.solana?.isPhantom) return alert("Phantom not found");
        try {{
            const response = await window.solana.connect();
            const publicKey = response.publicKey.toString();
            const message = `SolSocial Auth ${{Date.now()}}`;
            const signedMessage = await window.solana.signMessage(new TextEncoder().encode(message));
            window.parent.postMessage({{
                type: "walletConnected",
                publicKey: publicKey,
                signedMessage: Array.from(signedMessage.signature),
                message: message
            }}, "*");
        }} catch (error) {{
            console.error(error);
        }}
    }}
    document.getElementById("connect-button").addEventListener("click", connectWallet);
    </script>
    <button id="connect-button" class="connect-button">
        <img src="https://phantom.app/favicon.ico" width="20">
        Connect Wallet
    </button>
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
    }}
    </style>
    """, height=100)

async def auth_wallet(wallet: str, sig: list, msg: str, hcaptcha_token: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{BACKEND_URL}/auth/wallet",
                data={
                    "wallet_address": wallet,
                    "signed_message": str(sig),
                    "message": msg,
                    "hcaptcha_token": hcaptcha_token
                }
            )
            if r.status_code == 200:
                data = r.json()
                st.session_state.user_data = {
                    "user_id": wallet,
                    "wallet_address": wallet,
                    "auth_token": data.get("access_token")
                }
                return True
            else:
                st.error(f"Authentication failed: {r.text}")
                return False
    except Exception as e:
        st.error(f"Error during authentication: {str(e)}")
        return False

async def fetch_posts() -> list:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{BACKEND_URL}/posts")
            if r.status_code == 200:
                return r.json().get("posts", [])
            return []
    except Exception as e:
        st.error(f"Error fetching posts: {str(e)}")
        return []

async def submit_post(content: str, author: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{BACKEND_URL}/posts",
                json={
                    "content": content,
                    "author": author
                },
                headers={"Authorization": f"Bearer {st.session_state.user_data['auth_token']}"}
            )
            if r.status_code == 200:
                return True
            st.error(f"Post submission failed: {r.text}")
            return False
    except Exception as e:
        st.error(f"Error submitting post: {str(e)}")
        return False

async def render_feed():
    st.title("Home")
    st.write(f"Welcome, {st.session_state.user_data['wallet_address'][:6]}...{st.session_state.user_data['wallet_address'][-4:]}")
    
    with st.form("post_form"):
        content = st.text_area("What's on your mind?", max_chars=280)
        if st.form_submit_button("Post") and content:
            if await submit_post(content, st.session_state.user_data["wallet_address"]):
                st.rerun()

    posts = await fetch_posts()
    for post in posts:
        with st.container(border=True):
            st.write(f"**{post['author_wallet'][:6]}...{post['author_wallet'][-4:]}**")
            st.write(post['content'])
            st.caption(post['created_at'])

async def main():
    if not st.session_state.get('backend_checked'):
        if not await check_backend():
            st.error("Backend service unavailable")
            st.stop()
        st.session_state.backend_checked = True

    if st.session_state.user_data["auth_token"]:
        st.sidebar.write(f"User: {st.session_state.user_data['wallet_address'][:6]}...{st.session_state.user_data['wallet_address'][-4:]}")
        if st.sidebar.button("Logout"):
            clear_session()
            st.rerun()
        await render_feed()
    else:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.markdown("## Welcome to SolSocial")
            st.markdown("Connect your wallet to get started")
            show_captcha()
        with col2:
            st.image("https://i.ibb.co/YBngK5s6/background-jpg.jpg", width=300)
        
        wallet_connector()
        if st.session_state.get("wallet_connected"):
            if await auth_wallet(
                st.session_state["wallet_address"],
                st.session_state["signed_message"],
                st.session_state["message"],
                st.session_state["hcaptcha_token"]
            ):
                st.rerun()

components.html("""
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
""", height=0)

if __name__ == "__main__":
    asyncio.run(main())
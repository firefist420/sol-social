import streamlit as st
import httpx
import os
import asyncio
from dotenv import load_dotenv
import streamlit.components.v1 as components

load_dotenv()
BACKEND_URL = os.getenv("BACKEND_URL")
HCAPTCHA_SITEKEY = os.getenv("HCAPTCHA_SITEKEY")

st.set_page_config(page_title="SolSocial", layout="wide", page_icon="🚀")

def init_session():
    required_keys = {
        "user_data": {"wallet_address": "", "auth_token": None},
        "wallet_connected": False,
        "hcaptcha_verified": False,
        "hcaptcha_token": None,
        "signed_message": None,
        "message": None
    }
    for key, default_value in required_keys.items():
        if key not in st.session_state:
            st.session_state[key] = default_value

init_session()

def set_background():
    st.markdown("""
    <style>
    .stApp {
        background-image: url('https://i.ibb.co/YBngK5s6/background-jpg.jpg');
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }
    .auth-container {
        position: absolute;
        top: 20px;
        left: 20px;
        z-index: 100;
        display: flex;
        flex-direction: column;
        gap: 15px;
        background-color: rgba(0,0,0,0.8);
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        width: 300px;
    }
    .captcha-instructions {
        color: white !important;
        font-family: 'Arial', sans-serif;
        font-size: 24px;
        font-weight: bold;
        margin: 0 0 15px 0;
        text-align: center;
    }
    .connect-button {
        background-color: #7B2CBF;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 12px 0;
        font-size: 16px;
        font-weight: bold;
        cursor: pointer;
        display: none;
        justify-content: center;
        align-items: center;
        gap: 8px;
        width: 100%;
        transition: all 0.3s ease;
    }
    .connect-button:hover {
        background-color: #9D4EDD;
        transform: translateY(-2px);
    }
    .connect-button img {
        height: 20px;
    }
    .h-captcha {
        margin: 0 auto;
    }
    </style>
    """, unsafe_allow_html=True)

set_background()

async def check_backend():
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BACKEND_URL}/health")
            return response.status_code == 200
    except Exception as e:
        st.error(f"Backend connection error: {str(e)}")
        return False

def show_auth_components():
    components.html(f"""
    <div class="auth-container">
        <p class="captcha-instructions">Complete the captcha to connect your wallet</p>
        <script src="https://js.hcaptcha.com/1/api.js" async defer></script>
        <div class="h-captcha" data-sitekey="{HCAPTCHA_SITEKEY}" data-callback="onCaptchaSubmit"></div>
        <button id="connect-button" class="connect-button">
            <img src="https://i.ibb.co/fd1PzFX9/connect-wallet-button.png" alt="Wallet">
            Connect Wallet
        </button>
        <script>
        function onCaptchaSubmit(token) {{
            window.parent.postMessage({{
                type: "hcaptcha_verified",
                token: token,
                verified: true
            }}, "*");
            document.getElementById("connect-button").style.display = "flex";
        }}
        
        window.hcaptchaOnLoad = function() {{
            hcaptcha.render('h-captcha', {{
                sitekey: '{HCAPTCHA_SITEKEY}',
                callback: onCaptchaSubmit
            }});
        }};
        
        async function connectWallet() {{
            try {{
                const provider = window.solana;
                if (!provider?.isPhantom) {{
                    alert("Phantom wallet not found. Please install Phantom extension.");
                    return;
                }}
                
                const response = await provider.connect();
                const publicKey = response.publicKey.toString();
                const message = `SolSocial Auth ${{Date.now()}}`;
                const encodedMessage = new TextEncoder().encode(message);
                const signedMessage = await provider.signMessage(encodedMessage);
                
                window.parent.postMessage({{
                    type: "walletConnected",
                    publicKey: publicKey,
                    signedMessage: Array.from(signedMessage.signature),
                    message: message
                }}, "*");
                
            }} catch (error) {{
                console.error("Wallet connection error:", error);
                alert("Failed to connect wallet: " + error.message);
            }}
        }}
        
        document.getElementById("connect-button").addEventListener("click", connectWallet);
        </script>
    </div>
    """, height=280)

async def auth_wallet(wallet, sig, msg, hcaptcha_token):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{BACKEND_URL}/auth/wallet",
                json={
                    "wallet_address": wallet,
                    "signed_message": sig,
                    "message": msg,
                    "hcaptcha_token": hcaptcha_token
                }
            )
            
            if response.status_code == 200:
                st.session_state.user_data = {
                    "wallet_address": wallet,
                    "auth_token": response.json().get("access_token")
                }
                st.rerun()
                return True
            else:
                error_msg = response.json().get("detail", "Authentication failed")
                st.error(f"Error: {error_msg}")
                return False
                
    except Exception as e:
        st.error(f"Error: {str(e)}")
        return False

async def main():
    if not await check_backend():
        st.stop()

    show_auth_components()

    if st.session_state.hcaptcha_verified and st.session_state.wallet_connected:
        if st.session_state.hcaptcha_token and st.session_state.user_data["wallet_address"]:
            await auth_wallet(
                st.session_state.user_data["wallet_address"],
                st.session_state.signed_message,
                st.session_state.message,
                st.session_state.hcaptcha_token
            )

    if st.session_state.user_data["auth_token"]:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.title("SolSocial Feed")
            with st.form("post_form"):
                content = st.text_area("What's happening?")
                if st.form_submit_button("Post"):
                    pass

components.html("""
<script src="https://unpkg.com/@solana/web3.js@latest/lib/index.iife.min.js"></script>
<script>
window.addEventListener("message", (event) => {
    if (event.data.type === "walletConnected") {
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: {
                wallet_connected: true,
                wallet_address: event.data.publicKey,
                signed_message: event.data.signedMessage,
                message: event.data.message
            }
        }, "*");
    }
    if (event.data.type === "hcaptcha_verified") {
        window.parent.postMessage({
            type: "streamlit:setComponentValue",
            value: {
                hcaptcha_token: event.data.token,
                hcaptcha_verified: true
            }
        }, "*");
    }
});
</script>
""", height=0)

if __name__ == "__main__":
    asyncio.run(main())
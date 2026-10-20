import streamlit as st
from chain import ask

st.set_page_config(page_title="Assistant Opérateur", page_icon="🛠️")
st.title("Assistant Opérateur — RESILIENCE-ALPHA")
st.caption("Pose une question sur les procédures d'incident.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if question := st.chat_input("Ta question..."):
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        with st.spinner("Recherche dans les procédures..."):
            reponse = ask(question)
            st.markdown(reponse)
    st.session_state.messages.append({"role": "assistant", "content": reponse})

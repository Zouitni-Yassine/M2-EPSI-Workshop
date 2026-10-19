import streamlit as st
from chain import ask

st.set_page_config(page_title="Assistant Opérateur", page_icon="🛠️")
st.title("Assistant Opérateur — RESILIENCE-ALPHA")
st.caption("Pose une question sur les procédures d'incident.")

question = st.text_input("Ta question :")

if question:
    with st.spinner("Recherche dans les procédures..."):
        st.write(ask(question))

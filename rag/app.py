import asyncio

import streamlit as st
from chain import ask
from agent import repondre

st.set_page_config(page_title="Assistant Opérateur", page_icon="🛠️")
st.title("Assistant Opérateur — RESILIENCE-ALPHA")
st.caption("Pose une question sur les procédures d'incident.")

# Avec l'état du système : l'agent consulte aussi la supervision (outils MCP en lecture seule)
avec_etat = st.toggle("Avec l'état du système (supervision, lecture seule)", value=False)

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
        if avec_etat:
            with st.spinner("Consultation de la supervision et des procédures..."):
                resultat = asyncio.run(repondre(question))
                reponse = resultat["answer"]
                st.markdown(reponse)
                st.caption(f"Outils : {', '.join(resultat['tools']) or 'aucun'} · "
                           f"{resultat['model']} · {resultat['duration_s']} s")
        else:
            with st.spinner("Recherche dans les procédures..."):
                reponse = ask(question)
                st.markdown(reponse)
    st.session_state.messages.append({"role": "assistant", "content": reponse})

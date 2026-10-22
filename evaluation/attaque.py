import time, threading, requests

BASE = "http://localhost:8000"
stop = False
CIBLES = ["/api/status", "/api/payment_intents", "/api/balance",
          "/api/payment_intents/xxxxx", "/api/paypal/orders"]

def worker():
    i = 0
    while not stop:
        url = BASE + CIBLES[i % len(CIBLES)]
        try:
            if url.endswith("payment_intents"):
                requests.post(url, json={"amount": -1}, timeout=0.3)
            else:
                requests.get(url, timeout=0.3)
        except Exception:
            pass
        i += 1

print(">>> Phase 1 : trafic normal (20 s)")
time.sleep(20)
debut = round(time.time(), 1)
print(f">>> ATTAQUE INTENSE debut t={debut}")
threads = [threading.Thread(target=worker, daemon=True) for _ in range(250)]
for t in threads: t.start()
time.sleep(45)
stop = True
fin = round(time.time(), 1)
print(f">>> ATTAQUE fin t={fin}")
print(f"=== VERITE TERRAIN : attaque de {debut} a {fin} ===")
time.sleep(5)

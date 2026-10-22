"""Optional loopback-only SSH transport. No passwords are stored."""
import getpass
import select
import socketserver
import threading


class SSHRelay:
    def __init__(self, host, user, target, known_hosts):
        import paramiko
        self.client = paramiko.SSHClient()
        self.client.load_host_keys(str(known_hosts))
        self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
        self.client.connect(host, username=user,
                            password=getpass.getpass("Mot de passe SSH du relais : "),
                            look_for_keys=False, allow_agent=False, timeout=8)
        transport = self.client.get_transport()

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                channel = None
                try:
                    channel = transport.open_channel("direct-tcpip", target, self.client_address, timeout=8)
                    while True:
                        ready, _, _ = select.select([self.request, channel], [], [], 10)
                        if not ready:
                            break
                        for src in ready:
                            data = src.recv(65536)
                            if not data:
                                return
                            (channel if src is self.request else self.request).sendall(data)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                    # Normal TLS client teardown; HTTP outcome is recorded by the runner.
                    pass
                finally:
                    if channel is not None:
                        channel.close()

        class Server(socketserver.ThreadingTCPServer):
            daemon_threads = True
        self.server = Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.client.close()
        self.thread.join(timeout=2)

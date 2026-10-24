package com.suji;

import android.util.Log;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;

/**
 * Tiny LAN control page for playback speed.
 *
 * GET /              -> page with 1x / 1.25x / 1.5x / 2x buttons
 * GET /speed?v=1.5   -> set speed, returns the new state as JSON
 * GET /state         -> current state as JSON
 */
public final class Web {
    private static final String TAG = "SUJIDBG";
    private static final int PORT = 8099;

    private static ServerSocket server;

    private Web() {}

    public static void start() {
        if (server != null) {
            return;
        }
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                loop();
            }
        }, "suji-web");
        t.setDaemon(true);
        t.start();
    }

    private static void loop() {
        try {
            server = new ServerSocket(PORT);
            Log.i(TAG, "WEB listening on " + PORT);
            while (true) {
                final Socket socket = server.accept();
                Thread h = new Thread(new Runnable() {
                    @Override
                    public void run() {
                        handle(socket);
                    }
                });
                h.setDaemon(true);
                h.start();
            }
        } catch (Throwable t) {
            Log.i(TAG, "WEB stopped: " + t);
        }
    }

    private static void handle(Socket socket) {
        try {
            socket.setSoTimeout(5000);
            BufferedReader in = new BufferedReader(new InputStreamReader(socket.getInputStream(), "UTF-8"));
            String line = in.readLine();
            if (line == null) {
                socket.close();
                return;
            }
            String path = "/";
            String[] parts = line.split(" ");
            if (parts.length >= 2) {
                path = parts[1];
            }
            while (true) {
                String h = in.readLine();
                if (h == null || h.isEmpty()) {
                    break;
                }
            }

            String body;
            String type = "text/html; charset=utf-8";
            if (path.startsWith("/speed")) {
                float v = parseSpeed(path);
                if (v > 0f) {
                    Speed.setFromOutside(v);
                }
                body = state();
                type = "application/json; charset=utf-8";
            } else if (path.startsWith("/state")) {
                body = state();
                type = "application/json; charset=utf-8";
            } else {
                body = page();
            }
            write(socket, body, type);
        } catch (Throwable t) {
            Log.i(TAG, "WEB request failed: " + t);
            try {
                socket.close();
            } catch (Throwable ignored) {
            }
        }
    }

    private static float parseSpeed(String path) {
        int i = path.indexOf("v=");
        if (i < 0) {
            return -1f;
        }
        String raw = path.substring(i + 2);
        int amp = raw.indexOf('&');
        if (amp >= 0) {
            raw = raw.substring(0, amp);
        }
        try {
            return Float.parseFloat(URLDecoder.decode(raw, "UTF-8"));
        } catch (Throwable t) {
            return -1f;
        }
    }

    private static String state() {
        return "{\"speed\":" + Speed.CURRENT + ",\"player\":" + (Speed.player != null) + "}";
    }

    private static void write(Socket socket, String body, String type) throws Exception {
        byte[] bytes = body.getBytes("UTF-8");
        OutputStream out = socket.getOutputStream();
        String head = "HTTP/1.1 200 OK\r\n"
                + "Content-Type: " + type + "\r\n"
                + "Content-Length: " + bytes.length + "\r\n"
                + "Cache-Control: no-store\r\n"
                + "Connection: close\r\n\r\n";
        out.write(head.getBytes("UTF-8"));
        out.write(bytes);
        out.flush();
        socket.close();
    }

    private static String page() {
        return "<!doctype html><html><head><meta charset=utf-8>"
                + "<meta name=viewport content='width=device-width,initial-scale=1'>"
                + "<title>Playback speed</title>"
                + "<style>"
                + "body{background:#0b0b0b;color:#eee;font-family:-apple-system,Roboto,sans-serif;"
                + "margin:0;padding:28px;display:flex;flex-direction:column;gap:18px;align-items:center}"
                + "h1{font-size:20px;font-weight:600;margin:8px 0 4px}"
                + "p{color:#888;font-size:13px;margin:0}"
                + ".row{display:flex;gap:10px;flex-wrap:wrap;justify-content:center;margin-top:8px}"
                + "button{font-size:20px;padding:16px 22px;border-radius:12px;border:1px solid #333;"
                + "background:#1a1a1a;color:#ddd;min-width:96px}"
                + "button.on{background:#e50914;border-color:#e50914;color:#fff}"
                + "</style></head><body>"
                + "<h1>Playback speed</h1>"
                + "<p id=s>connecting…</p>"
                + "<div class=row id=r></div>"
                + "<p>Changes apply to the TV immediately.</p>"
                + "<script>"
                + "const steps=[1,1.25,1.5,2];"
                + "async function refresh(){try{const j=await (await fetch('/state')).json();"
                + "document.getElementById('s').textContent='TV is at '+j.speed+'x'+(j.player?'':' (no player yet)');"
                + "document.querySelectorAll('button').forEach(b=>b.classList.toggle('on',parseFloat(b.dataset.v)===j.speed));"
                + "}catch(e){document.getElementById('s').textContent='TV unreachable';}}"
                + "for(const v of steps){const b=document.createElement('button');b.textContent=v+'x';b.dataset.v=v;"
                + "b.onclick=async()=>{await fetch('/speed?v='+v);refresh();};document.getElementById('r').appendChild(b);}"
                + "refresh();setInterval(refresh,2000);"
                + "</script></body></html>";
    }
}

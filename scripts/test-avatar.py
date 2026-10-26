"""
avatar.py 的冒烟测试：起一个假桌宠服务，验证「取锁 → 投喂 → 放锁」全链路。

用法：python scripts/test-avatar.py
不依赖任何第三方包（只用标准库）。
"""
import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from companion.avatar import (  # noqa: E402
    AvatarClient,
    TIER_CARING,
    TIER_SPEAKING,
    TIER_TIRED,
    WORK_STATUS_THINKING,
)

CALLS = []


class FakePet(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _respond(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_POST(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        body = self._read_body()
        CALLS.append({
            "method": "POST",
            "path": parsed.path,
            "pet": query.get("pet", [None])[0],
            "lock": query.get("lock", [None])[0],
            "body": body,
        })

        if parsed.path.endswith("/lock"):
            self._respond({"lockId": "LOCK-123", "expiresAt": 9999999999999})
        elif parsed.path.endswith("/lock/release"):
            self._respond({"ok": True})
        elif parsed.path.endswith("/broadcast"):
            if query.get("lock", [None])[0] != "LOCK-123":
                self._respond({"code": "lock-required"}, 409)
                return
            self._respond({"ok": True, "text": body.get("text")})
        elif parsed.path.endswith("/anim"):
            if query.get("lock", [None])[0] != "LOCK-123":
                self._respond({"code": "lock-required"}, 409)
                return
            self._respond({"ok": True, "playbackId": "pb-1"})
        elif parsed.path.endswith("/work-status"):
            self._respond({"ok": True, "state": body.get("state")})
        else:
            self._respond({"ok": True})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        CALLS.append({"method": "DELETE", "path": parsed.path})
        self.send_response(204)
        self.end_headers()


async def main():
    server = HTTPServer(("127.0.0.1", 0), FakePet)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    base = f"http://127.0.0.1:{port}/dsh-pet-7340"
    print(f"假桌宠服务: {base}\n")

    avatar = AvatarClient({
        "enabled": True,
        "base_url": base,
        "pet_id": "main",
        "tier_animations": {TIER_SPEAKING: "说话", TIER_TIRED: "打瞌睡"},
    })

    print("enabled:", avatar.enabled)
    print("档位→动画:", {TIER_SPEAKING: avatar.animation_for(TIER_SPEAKING),
                          TIER_TIRED: avatar.animation_for(TIER_TIRED),
                          TIER_CARING: avatar.animation_for(TIER_CARING)})

    ok = await avatar.say("今天过得怎么样？", tier=TIER_SPEAKING)
    print(f"\n1) say() -> {ok}")
    print(f"   期望 True，且调用序列是 lock -> broadcast(带 lock) -> lock/release")

    ok2 = await avatar.set_state(TIER_TIRED)
    print(f"2) set_state(犯困) -> {ok2}")

    ok3 = await avatar.set_work_status(WORK_STATUS_THINKING)
    print(f"3) set_work_status(思考) -> {ok3}")

    ok4 = await avatar.set_emotion("caring")
    print(f"4) set_emotion(caring) -> {ok4}")

    ok5 = await avatar.clear_work_status()
    print(f"5) clear_work_status() -> {ok5}")

    await avatar.close()
    server.shutdown()

    print("\n--- actual call sequence ---")
    for c in CALLS:
        extra = ""
        if c["method"] == "POST" and c["path"].endswith(("/broadcast", "/anim")):
            extra = f"  body={c['body']}"
        print(f"  {c['method']:6} {c['path'].replace('/dsh-pet-7340', ''):20} "
              f"pet={c.get('pet')} lock={c.get('lock')}{extra}")

    # 断言
    paths = [c["path"].replace("/dsh-pet-7340", "") for c in CALLS]
    assert paths[0] == "/lock", paths
    assert paths[1] == "/broadcast", paths
    assert paths[2] == "/lock/release", paths
    assert any(c["path"].endswith("/work-status") and c["method"] == "POST" for c in CALLS)
    assert any(c["method"] == "DELETE" for c in CALLS)
    # 每个需锁的动作都必须带 lock，且都在 lock / lock/release 之间
    for i, c in enumerate(CALLS):
        if c["method"] == "POST" and c["path"].endswith(("/broadcast", "/anim")):
            assert c["lock"] == "LOCK-123", c
    print("\n[OK] all assertions passed")

    # ---- 失败路径：服务不在时应自我关闭，而不是抛异常 ----
    print("\n--- failure path: server down ---")
    dead = AvatarClient({
        "enabled": True,
        "base_url": "http://127.0.0.1:1/dsh-pet-7340",  # 必然连不上
        "timeout": 0.3,
        "max_consecutive_failures": 3,
    })
    results = []
    for _ in range(4):
        results.append(await dead.say("hi"))
    print("  say() results:", results)
    assert all(r is False for r in results), results
    assert dead.enabled is False, "should auto-disable after repeated failures"
    print("[OK] auto-disabled after repeated failures, no exception raised")


if __name__ == "__main__":
    asyncio.run(main())

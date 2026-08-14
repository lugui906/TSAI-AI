import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_pc_manager import AIManager
import threading
import queue

q = queue.Queue()
done = threading.Event()

def callback(output):
    q.put(output)
    done.set()

def log(msg):
    print(f"[LOG] {msg}")

print("开始系统优化...")
AIManager.ai_system_optimize(callback, log)
done.wait(timeout=300)
try:
    result = q.get_nowait()
    print("=== 优化结果 ===")
    print(result)
except queue.Empty:
    print("超时，未获得结果")

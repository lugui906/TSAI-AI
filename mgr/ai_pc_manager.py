#!/usr/bin/env python3
import sys
import os
import subprocess
import threading
import json
import psutil
import shutil
import time
import platform
from datetime import datetime

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Gdk', '4.0')
    gi.require_version('GdkPixbuf', '2.0')
    from gi.repository import Gtk, Gdk, GLib, GdkPixbuf
except Exception as e:
    print(f"Error loading GTK4: {e}")
    sys.exit(1)


class SystemInfo:
    @staticmethod
    def get_cpu_usage():
        return psutil.cpu_percent(interval=None)

    @staticmethod
    def get_cpu_count():
        return psutil.cpu_count(logical=True)

    @staticmethod
    def get_cpu_info():
        try:
            cpu_info = {}
            if hasattr(psutil, 'cpu_freq'):
                freq = psutil.cpu_freq()
                if freq:
                    cpu_info['max_freq'] = freq.max
                    cpu_info['current_freq'] = freq.current
            cpu_info['cores'] = psutil.cpu_count(logical=False)
            cpu_info['threads'] = psutil.cpu_count(logical=True)
            return cpu_info
        except:
            return {}

    @staticmethod
    def get_memory_info():
        mem = psutil.virtual_memory()
        return {
            'total': mem.total,
            'used': mem.used,
            'available': mem.available,
            'percent': mem.percent,
            'buffers': mem.buffers if hasattr(mem, 'buffers') else 0,
            'cached': mem.cached if hasattr(mem, 'cached') else 0,
            'shared': mem.shared if hasattr(mem, 'shared') else 0
        }

    @staticmethod
    def get_swap_info():
        swap = psutil.swap_memory()
        return {
            'total': swap.total,
            'used': swap.used,
            'free': swap.free,
            'percent': swap.percent,
            'sin': swap.sin,
            'sout': swap.sout
        }

    @staticmethod
    def get_disk_info():
        disk = shutil.disk_usage('/')
        return {
            'total': disk.total,
            'used': disk.used,
            'free': disk.free,
            'percent': (disk.used / disk.total) * 100
        }

    @staticmethod
    def get_all_disks():
        disks = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = shutil.disk_usage(part.mountpoint)
                disks.append({
                    'device': part.device,
                    'mountpoint': part.mountpoint,
                    'fstype': part.fstype,
                    'total': usage.total,
                    'used': usage.used,
                    'free': usage.free,
                    'percent': (usage.used / usage.total) * 100
                })
            except:
                continue
        return disks

    @staticmethod
    def get_cpu_temp():
        try:
            temp = psutil.sensors_temperatures()
            if 'coretemp' in temp:
                return temp['coretemp'][0].current
            elif 'cpu_thermal' in temp:
                return temp['cpu_thermal'][0].current
            elif 'acpitz' in temp:
                return temp['acpitz'][0].current
        except:
            pass
        return None

    @staticmethod
    def get_running_processes():
        return len(psutil.pids())

    @staticmethod
    def get_system_uptime():
        uptime = time.time() - psutil.boot_time()
        days = int(uptime // 86400)
        hours = int((uptime % 86400) // 3600)
        minutes = int((uptime % 3600) // 60)
        if days > 0:
            return f"{days}天 {hours}h {minutes}m"
        return f"{hours}h {minutes}m"

    @staticmethod
    def get_system_info():
        return {
            'platform': platform.system(),
            'platform_release': platform.release(),
            'platform_version': platform.version(),
            'architecture': platform.architecture()[0],
            'hostname': platform.node(),
            'processor': platform.processor()
        }

    @staticmethod
    def get_network_info():
        net = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        info = {}
        for interface, addresses in net.items():
            if interface.startswith('lo'):
                continue
            info[interface] = {
                'addresses': [a.address for a in addresses if a.family == 2],
                'status': stats[interface].isup if interface in stats else False,
                'speed': stats[interface].speed if interface in stats else 0
            }
        return info

    @staticmethod
    def get_network_io():
        return psutil.net_io_counters()

    @staticmethod
    def get_boot_time():
        return datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def get_users():
        return [u.name for u in psutil.users()]

    @staticmethod
    def get_high_memory_processes(limit=10):
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory': proc.info['memory_info'].rss,
                    'percent': proc.info['memory_info'].rss / psutil.virtual_memory().total * 100
                })
            except:
                continue
        processes.sort(key=lambda x: x['memory'], reverse=True)
        return processes[:limit]

    @staticmethod
    def format_bytes(bytes_value):
        if bytes_value < 1024:
            return f"{bytes_value} B"
        elif bytes_value < 1024 ** 2:
            return f"{bytes_value / 1024:.2f} KB"
        elif bytes_value < 1024 ** 3:
            return f"{bytes_value / (1024 ** 2):.2f} MB"
        else:
            return f"{bytes_value / (1024 ** 3):.2f} GB"

    @staticmethod
    def format_speed(bytes_per_sec):
        if bytes_per_sec < 1024:
            return f"{bytes_per_sec:.2f} B/s"
        elif bytes_per_sec < 1024 ** 2:
            return f"{bytes_per_sec / 1024:.2f} KB/s"
        else:
            return f"{bytes_per_sec / (1024 ** 2):.2f} MB/s"


class AIManager:
    @staticmethod
    def run_command_with_live_output(cmd, cmd_str, callback=None, log_callback=None):
        full_output = []
        
        def execute():
            try:
                if log_callback:
                    GLib.idle_add(log_callback, f"[执行中] {cmd_str}")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                for line in iter(process.stdout.readline, ''):
                    line = line.strip()
                    if line:
                        full_output.append(line)
                        if log_callback:
                            GLib.idle_add(log_callback, f"[输出] {line}")
                
                process.stdout.close()
                return_code = process.wait()
                
                output = '\n'.join(full_output)
                
                if return_code != 0 and output and "command not found" in output.lower():
                    if log_callback:
                        GLib.idle_add(log_callback, "[回退] 命令不存在，尝试其他方案...")
                    return None, True
                
                if log_callback:
                    GLib.idle_add(log_callback, f"[完成] 命令执行结束")
                
                GLib.idle_add(callback, output) if callback else None
                return output, False
            except FileNotFoundError:
                error = "[错误] 命令不存在"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error, True
            except Exception as e:
                error = f"[错误] {str(e)}"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error, False
        
        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
    
    @staticmethod
    def run_aim_command(command, args=None, callback=None, log_callback=None):
        cmd = ['aim', command]
        if args:
            cmd.extend(args)
        
        cmd_str = ' '.join(cmd)
        if log_callback:
            GLib.idle_add(log_callback, f"[命令] {cmd_str}")
        
        def execute():
            output, need_fallback = AIManager._run_command_sync(cmd, cmd_str, log_callback)
            
            if need_fallback:
                if log_callback:
                    GLib.idle_add(log_callback, "[回退] aim命令不存在，尝试使用Ollama...")
                AIManager._fallback_to_ollama(command, args, callback, log_callback)
                return
            
            GLib.idle_add(callback, output) if callback else None
        
        thread = threading.Thread(target=execute, daemon=True)
        thread.start()
    
    @staticmethod
    def _run_command_sync(cmd, cmd_str, log_callback=None):
        full_output = []
        
        try:
            if log_callback:
                GLib.idle_add(log_callback, f"[执行中] {cmd_str}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    full_output.append(line)
                    if log_callback:
                        GLib.idle_add(log_callback, f"[输出] {line}")
            
            process.stdout.close()
            return_code = process.wait()
            
            output = '\n'.join(full_output)
            
            if return_code != 0 and output and "command not found" in output.lower():
                return output, True
            
            if log_callback:
                GLib.idle_add(log_callback, f"[完成] 命令执行结束")
            
            return output, False
        except FileNotFoundError:
            error = "[错误] 命令不存在"
            if log_callback:
                GLib.idle_add(log_callback, error)
            return error, True
        except Exception as e:
            error = f"[错误] {str(e)}"
            if log_callback:
                GLib.idle_add(log_callback, error)
            return error, False

    @staticmethod
    def _fallback_to_ollama(command, args, callback=None, log_callback=None):
        if command == 'run' and args:
            prompt = ' '.join(args)
            AIManager.ollama_run_with_default_model(prompt, callback, log_callback)
    
    @staticmethod
    def ollama_run_with_default_model(prompt, callback=None, log_callback=None):
        default_model = 'llama3'
        
        def check_and_run():
            try:
                result = subprocess.run(
                    ['ollama', 'list'],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if default_model in result.stdout:
                    if log_callback:
                        GLib.idle_add(log_callback, f"[Ollama] 使用模型: {default_model}")
                    AIManager.ollama_run(default_model, prompt, callback, log_callback)
                else:
                    if log_callback:
                        GLib.idle_add(log_callback, f"[Ollama] 模型 {default_model} 未找到，尝试拉取...")
                    AIManager.ollama_pull(default_model, lambda output: AIManager.ollama_run(default_model, prompt, callback, log_callback), log_callback)
            except FileNotFoundError:
                error = "[错误] 未安装Ollama，请先安装: curl -fsSL https://ollama.com/install.sh | sh"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
        
        thread = threading.Thread(target=check_and_run, daemon=True)
        thread.start()

    @staticmethod
    @staticmethod
    def _run_cmd(cmd, desc, log_callback):
        if log_callback:
            GLib.idle_add(log_callback, f"[执行] {desc}")
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line and log_callback:
                    GLib.idle_add(log_callback, f"  {line}")
            process.stdout.close()
            process.wait()
        except Exception as e:
            if log_callback:
                GLib.idle_add(log_callback, f"[错误] {e}")

    @staticmethod
    def _run_aim_cmd(prompt, log_callback):
        if log_callback:
            GLib.idle_add(log_callback, "[AI] 正在分析...")
        try:
            cmd = ['aim', 'run', prompt]
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1
            )
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line and log_callback:
                    GLib.idle_add(log_callback, f"[AI] {line}")
            process.stdout.close()
            process.wait()
        except Exception as e:
            if log_callback:
                GLib.idle_add(log_callback, f"[AI错误] {e}")

    @staticmethod
    def _run_live(cmd_list, log_callback=None, done_callback=None):
        def execute():
            for cmd, desc in cmd_list:
                AIManager._run_cmd(cmd, desc, log_callback)
            if done_callback:
                GLib.idle_add(done_callback, "全部操作已完成")
        return execute

    @staticmethod
    def _run_ai_and_live(prompt, fix_cmds, log_callback=None, done_callback=None):
        def execute():
            AIManager._run_aim_cmd(prompt, log_callback)
            GLib.idle_add(log_callback, "[系统] AI分析完成，开始执行修复操作...")
            for cmd, desc in fix_cmds:
                AIManager._run_cmd(cmd, desc, log_callback)
            if done_callback:
                GLib.idle_add(done_callback, "全部操作已完成")
        return execute

    @staticmethod
    def ai_system_optimize(callback=None, log_callback=None):
        prompt = '你是一个智能系统优化助手。请分析当前系统并告诉你将执行哪些优化操作，包括清理垃圾、释放内存、优化启动项、修复配置问题。请先输出分析结果。'
        fix_cmds = [
            ("sudo apt-get clean -y 2>/dev/null", "清理 apt 缓存"),
            ("sudo apt-get autoremove -y 2>/dev/null", "清理孤立依赖"),
            ("sudo journalctl --vacuum-time=7d 2>/dev/null", "清理 7 天前的日志"),
            ("rm -rf ~/.cache/thumbnails/* ~/.local/share/Trash/* 2>/dev/null", "清理缩略图和回收站"),
            ("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1", "释放内存缓存"),
            ("sudo systemctl mask apt-daily.service --now 2>/dev/null", "禁用慢启动 apt-daily"),
            ("sudo systemctl mask NetworkManager-wait-online.service --now 2>/dev/null", "禁用网络等待服务"),
            ("sudo systemctl mask plymouth-quit-wait.service --now 2>/dev/null", "禁用开机画面等待"),
            ("echo '=== 系统优化全部完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_fault_diagnosis(callback=None, log_callback=None):
        prompt = '你是一个智能故障诊断助手。请分析系统日志和硬件状态，找出潜在问题，并输出分析结果和修复建议。'
        fix_cmds = [
            ("echo '=== 硬件信息 ===' && lspci -k | grep -E 'VGA|Network|Audio|Kernel driver' | head -20", "检测硬件状态"),
            ("sudo journalctl -p err -b --no-pager -n 30 2>/dev/null", "分析系统错误日志"),
            ("free -h", "检查内存状态"),
            ("echo '=== 诊断完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_performance_analysis(callback=None, log_callback=None):
        prompt = '你是一个智能性能分析助手。请分析 CPU、内存、磁盘的性能数据，找出瓶颈并输出优化建议。'
        fix_cmds = [
            ("echo '=== CPU 使用 TOP 10 ===' && ps aux --sort=-%cpu | head -11", "分析 CPU 占用"),
            ("echo '=== 内存使用 TOP 10 ===' && ps aux --sort=-%mem | head -11", "分析内存占用"),
            ("echo '=== 内存概况 ===' && free -h", "内存使用情况"),
            ("echo '=== 磁盘空间 ===' && df -h /", "磁盘空间"),
            ("iostat -x 1 2 2>/dev/null | tail -15 || echo 'iostat 不可用'", "分析磁盘 IO"),
            ("echo '=== 性能分析完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_security_scan(callback=None, log_callback=None):
        prompt = '你是一个智能安全扫描助手。请分析以下安全数据，找出风险并输出处理建议。'
        fix_cmds = [
            ("echo '=== 网络连接 ===' && ss -tuln", "检测网络连接状态"),
            ("echo '=== 监听端口 ===' && ss -tlnp 2>/dev/null | head -20", "检测监听端口"),
            ("echo '=== 进程 TOP 15 ===' && ps aux --sort=-%cpu | head -15", "检查异常进程"),
            ("sudo last -n 10 2>/dev/null", "检查登录记录"),
            ("sudo apt-get check 2>/dev/null", "检查系统完整性"),
            ("echo '=== 安全扫描完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_drive_update(callback=None, log_callback=None):
        prompt = '你是一个智能驱动管理助手。请根据检测到的硬件驱动版本信息，分析哪些驱动需要更新，并输出详细建议。'
        fix_cmds = [
            ("echo '=== 显卡 ===' && lspci -k | grep -A3 'VGA\\|3D'", "检测显卡驱动"),
            ("echo '=== WiFi ===' && lspci -k | grep -A3 Network", "检测 WiFi 驱动"),
            ("echo '=== 音频 ===' && lspci -k | grep -A3 Audio", "检测音频驱动"),
            ("echo '=== 已加载驱动模块 ===' && lsmod | grep -E 'i915|iwlwifi|btusb|nvme|snd' | head -10", "已加载驱动模块"),
            ("dpkg -l intel-microcode 2>/dev/null | tail -2", "CPU 微码版本"),
            ("sudo fwupdmgr refresh 2>/dev/null && sudo fwupdmgr get-updates 2>/dev/null | head -20", "检查固件更新"),
            ("echo '=== 驱动检测完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_software_management(callback=None, log_callback=None):
        prompt = '你是一个智能软件管理助手。请分析系统软件包状态，输出可升级软件包数量和依赖情况，并给出升级建议。'
        fix_cmds = [
            ("echo '=== 可升级包统计 ===' && apt list --upgradable 2>/dev/null | tail -1", "检查可升级软件包"),
            ("sudo apt-get check 2>/dev/null", "检查依赖关系"),
            ("echo '=== 开始升级 ===' && sudo apt-get upgrade -y 2>&1 | tail -5", "自动升级所有软件包"),
            ("sudo apt-get autoremove -y 2>/dev/null && sudo apt-get clean -y 2>/dev/null", "清理无用包和缓存"),
            ("echo '=== 软件升级完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_network_optimize(callback=None, log_callback=None):
        prompt = '你是一个智能网络优化助手。请分析网络配置和连接状态，找出问题并给出优化建议。'
        fix_cmds = [
            ("echo '=== 网络接口 ===' && ip addr | grep -E '^[0-9]|inet '", "检测网络接口"),
            ("echo '=== DNS 配置 ===' && cat /etc/resolv.conf 2>/dev/null", "检查 DNS 配置"),
            ("echo '=== 网络延迟 ===' && ping -c 4 114.114.114.114 2>&1 | tail -3", "检测网络延迟"),
            ("echo '=== 网络连接统计 ===' && ss -s", "网络连接统计"),
            ("echo '=== 网络优化完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_disk_defragment(callback=None, log_callback=None):
        prompt = '你是一个智能磁盘管理助手。请分析磁盘使用情况和文件系统状态，输出优化建议。'
        fix_cmds = [
            ("echo '=== 磁盘使用 ===' && df -h /", "检查磁盘使用"),
            ("echo '=== 磁盘分区 ===' && lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT 2>/dev/null", "磁盘分区信息"),
            ("sudo fstrim -v / 2>/dev/null || echo 'TRIM 操作跳过（SSD 不需要碎片整理）'", "执行 TRIM 优化"),
            ("echo '=== 大文件 TOP 10 ===' && find /home -type f -exec ls -lh {} \\; 2>/dev/null | sort -rh -k5 | head -10", "查找大文件"),
            ("echo '=== 磁盘优化完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_startup_optimize(callback=None, log_callback=None):
        prompt = '你是一个智能启动优化助手。请分析开机启动项和服务耗时，输出优化建议并自动执行。'
        fix_cmds = [
            ("systemd-analyze 2>/dev/null", "分析开机耗时"),
            ("systemd-analyze blame 2>/dev/null | head -10", "分析慢启动服务"),
            ("sudo systemctl mask apt-daily.service --now 2>/dev/null && sudo systemctl mask apt-daily-upgrade.service --now 2>/dev/null && sudo systemctl mask NetworkManager-wait-online.service --now 2>/dev/null && sudo systemctl mask plymouth-quit-wait.service --now 2>/dev/null && echo '已禁用慢启动服务'", "自动禁用慢速服务"),
            ("echo '=== 启动优化完成，建议重启 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_memory_optimize(callback=None, log_callback=None):
        prompt = '你是一个智能内存优化助手。请分析当前内存使用情况，输出优化建议并自动执行。'
        fix_cmds = [
            ("free -h", "记录优化前内存"),
            ("ps aux --sort=-%mem | head -11", "分析内存占用进程"),
            ("sync && echo 3 | sudo tee /proc/sys/vm/drop_caches > /dev/null 2>&1", "释放内存缓存"),
            ("free -h", "查看优化后内存"),
            ("swapon --show 2>/dev/null", "检查交换分区"),
            ("echo '=== 内存优化完成 ==='", ""),
        ]
        threading.Thread(target=AIManager._run_ai_and_live(prompt, fix_cmds, log_callback, callback), daemon=True).start()

    @staticmethod
    def ai_question_answer(question, callback=None, log_callback=None):
        AIManager.run_aim_command('run', [question], callback, log_callback)

    @staticmethod
    def repair_system(callback=None, log_callback=None):
        AIManager.run_aim_command('fix', callback=callback, log_callback=log_callback)

    @staticmethod
    def debug_system(callback=None, log_callback=None):
        AIManager.run_aim_command('debug', callback=callback, log_callback=log_callback)

    @staticmethod
    def clean_disk(callback=None, log_callback=None):
        AIManager.run_aim_command('run', ['清理系统缓存、临时文件、日志文件，释放磁盘空间'], callback, log_callback)

    @staticmethod
    def get_ai_models(callback=None, log_callback=None):
        AIManager.run_ollama_command('list', callback, log_callback)

    @staticmethod
    def run_ollama_command(command, callback=None, log_callback=None):
        cmd = ['ollama'] + command.split()
        
        cmd_str = ' '.join(cmd)
        if log_callback:
            GLib.idle_add(log_callback, f"[Ollama命令] {cmd_str}")
        
        def execute():
            full_output = []
            
            try:
                if log_callback:
                    GLib.idle_add(log_callback, f"[Ollama执行中] {cmd_str}")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                for line in iter(process.stdout.readline, ''):
                    line = line.strip()
                    if line:
                        full_output.append(line)
                        if log_callback:
                            GLib.idle_add(log_callback, f"[输出] {line}")
                
                process.stdout.close()
                return_code = process.wait()
                
                output = '\n'.join(full_output)
                
                if log_callback:
                    GLib.idle_add(log_callback, f"[完成] 命令执行结束")
                
                GLib.idle_add(callback, output) if callback else None
                return output
            except subprocess.TimeoutExpired:
                error = f"[超时] 命令执行超过180秒: {cmd_str}"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
            except FileNotFoundError:
                error = f"[错误] 未找到 ollama 命令，请先安装 Ollama"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
            except Exception as e:
                error = f"[错误] {str(e)}"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
        
        thread = threading.Thread(target=execute, daemon=True)
        thread.start()

    @staticmethod
    def ollama_pull(model_name, callback=None, log_callback=None):
        AIManager.run_ollama_command(f'pull {model_name}', callback, log_callback)

    @staticmethod
    def ollama_run(model_name, prompt, callback=None, log_callback=None):
        cmd = ['ollama', 'run', model_name, prompt]
        
        cmd_str = ' '.join(cmd[:3]) + ' ' + prompt[:30] + '...' if len(prompt) > 30 else ' '.join(cmd)
        if log_callback:
            GLib.idle_add(log_callback, f"[Ollama命令] {cmd_str}")
        
        def execute():
            full_output = []
            
            try:
                if log_callback:
                    GLib.idle_add(log_callback, f"[Ollama执行中] 正在与 {model_name} 对话...")
                
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                
                for line in iter(process.stdout.readline, ''):
                    line = line.strip()
                    if line:
                        full_output.append(line)
                        if log_callback:
                            GLib.idle_add(log_callback, f"[输出] {line}")
                
                process.stdout.close()
                return_code = process.wait()
                
                output = '\n'.join(full_output)
                
                if log_callback:
                    GLib.idle_add(log_callback, f"[完成] 命令执行结束")
                
                GLib.idle_add(callback, output) if callback else None
                return output
            except subprocess.TimeoutExpired:
                error = f"[超时] 命令执行超过300秒: {cmd_str}"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
            except FileNotFoundError:
                error = f"[错误] 未找到 ollama 命令"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
            except Exception as e:
                error = f"[错误] {str(e)}"
                if log_callback:
                    GLib.idle_add(log_callback, error)
                GLib.idle_add(callback, error) if callback else None
                return error
        
        thread = threading.Thread(target=execute, daemon=True)
        thread.start()

    @staticmethod
    def ollama_delete(model_name, callback=None, log_callback=None):
        AIManager.run_ollama_command(f'delete {model_name}', callback, log_callback)


class DashboardPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="首页概览")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        self.stats_grid = Gtk.Grid(column_spacing=16, row_spacing=12)
        
        self.cpu_stat = self._create_stat_card("CPU", "#4CAF50")
        self.mem_stat = self._create_stat_card("内存", "#2196F3")
        self.disk_stat = self._create_stat_card("磁盘", "#FF9800")
        self.process_stat = self._create_stat_card("进程", "#9C27B0")
        
        self.stats_grid.attach(self.cpu_stat['box'], 0, 0, 1, 1)
        self.stats_grid.attach(self.mem_stat['box'], 1, 0, 1, 1)
        self.stats_grid.attach(self.disk_stat['box'], 0, 1, 1, 1)
        self.stats_grid.attach(self.process_stat['box'], 1, 1, 1, 1)
        
        self.append(self.stats_grid)
        
        quick_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        quick_actions.set_margin_top(10)
        
        actions = [
            ("AI系统优化", "#4CAF50"),
            ("AI故障诊断", "#FF9800"),
            ("AI安全扫描", "#9C27B0"),
            ("内存优化", "#FF5722"),
        ]
        
        action_callbacks = {
            "AI系统优化": AIManager.ai_system_optimize,
            "AI故障诊断": AIManager.ai_fault_diagnosis,
            "AI安全扫描": AIManager.ai_security_scan,
            "内存优化": AIManager.ai_memory_optimize,
        }
        
        for label, color in actions:
            btn = Gtk.Button(label=label)
            btn.set_size_request(140, 40)
            btn.connect("clicked", self._on_quick_action, label, action_callbacks[label])
            quick_actions.append(btn)
        
        self.append(quick_actions)
        
        ai_output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ai_output_box.set_margin_top(20)
        
        ai_title = Gtk.Label(label="AI输出")
        ai_title.add_css_class("heading")
        ai_output_box.append(ai_title)
        
        self.ai_output_text = Gtk.TextView()
        self.ai_output_text.set_editable(False)
        self.ai_output_text.set_cursor_visible(False)
        self.ai_output_buffer = self.ai_output_text.get_buffer()
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.ai_output_text)
        scroll.set_size_request(-1, 150)
        
        ai_output_box.append(scroll)
        
        self.append(ai_output_box)
        
        psutil.cpu_percent(interval=None)
        
        def delayed_update():
            cpu = SystemInfo.get_cpu_usage()
            print(f"CPU: {cpu}%")
            mem = SystemInfo.get_memory_info()
            print(f"Memory: {mem['percent']}%")
            disk = SystemInfo.get_disk_info()
            print(f"Disk: {disk['percent']}%")
            processes = SystemInfo.get_running_processes()
            print(f"Processes: {processes}")
            
            self.cpu_stat['value_label'].set_label(f"{cpu:.1f}%")
            self.cpu_stat['bar'].set_fraction(cpu / 100)
            
            self.mem_stat['value_label'].set_label(f"{SystemInfo.format_bytes(mem['used'])}")
            self.mem_stat['bar'].set_fraction(mem['percent'] / 100)
            
            self.disk_stat['value_label'].set_label(f"{disk['percent']:.1f}%")
            self.disk_stat['bar'].set_fraction(disk['percent'] / 100)
            
            self.process_stat['value_label'].set_label(f"{processes}")
            self.process_stat['bar'].set_fraction(min(processes / 500, 1))
            
            GLib.timeout_add(2000, self._update_stats)
            return False
        
        GLib.timeout_add(1000, delayed_update)

    def _create_stat_card(self, title, color):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("heading")
        
        value_label = Gtk.Label(label="--")
        value_label.set_css_classes(["title"])
        
        bar = Gtk.ProgressBar()
        bar.set_size_request(-1, 12)
        
        css = f"""
        progressbar progress {{ background-color: {color}; }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        bar.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        box.append(title_label)
        box.append(value_label)
        box.append(bar)
        
        return {'box': box, 'value_label': value_label, 'bar': bar}

    def _update_stats(self):
        cpu = SystemInfo.get_cpu_usage()
        mem = SystemInfo.get_memory_info()
        disk = SystemInfo.get_disk_info()
        processes = SystemInfo.get_running_processes()
        
        self.cpu_stat['value_label'].set_label(f"{cpu:.1f}%")
        self.cpu_stat['bar'].set_fraction(cpu / 100)
        
        self.mem_stat['value_label'].set_label(f"{SystemInfo.format_bytes(mem['used'])}")
        self.mem_stat['bar'].set_fraction(mem['percent'] / 100)
        
        self.disk_stat['value_label'].set_label(f"{disk['percent']:.1f}%")
        self.disk_stat['bar'].set_fraction(disk['percent'] / 100)
        
        self.process_stat['value_label'].set_label(f"{processes}")
        self.process_stat['bar'].set_fraction(min(processes / 500, 1))
        
        return True

    def update_ai_output(self, text):
        end_iter = self.ai_output_buffer.get_end_iter()
        self.ai_output_buffer.insert(end_iter, text + "\n")
        
        end_iter = self.ai_output_buffer.get_end_iter()
        self.ai_output_text.scroll_to_iter(end_iter, 0, False, 0, 0)

    def _on_quick_action(self, btn, label, callback):
        def on_result(output):
            GLib.idle_add(self.update_ai_output, f"[{datetime.now().strftime('%H:%M:%S')}] 执行完成: {output[:200]}")
        
        def on_log(msg):
            GLib.idle_add(self.update_ai_output, f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
        
        self.update_ai_output(f"[{datetime.now().strftime('%H:%M:%S')}] 正在执行: {label}...")
        callback(on_result, on_log)


class SystemInfoPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="系统信息")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        notebook = Gtk.Notebook()
        
        basic_grid = self._create_basic_info()
        notebook.append_page(basic_grid, Gtk.Label(label="基本信息"))
        
        hardware_grid = self._create_hardware_info()
        notebook.append_page(hardware_grid, Gtk.Label(label="硬件信息"))
        
        self.append(notebook)

    def _create_basic_info(self):
        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        
        info = SystemInfo.get_system_info()
        uptime = SystemInfo.get_system_uptime()
        boot_time = SystemInfo.get_boot_time()
        
        rows = [
            ("操作系统", info['platform']),
            ("版本", info['platform_release']),
            ("内核版本", info['platform_version']),
            ("架构", info['architecture']),
            ("主机名", info['hostname']),
            ("系统运行", uptime),
            ("启动时间", boot_time),
        ]
        
        for i, (label, value) in enumerate(rows):
            grid.attach(Gtk.Label(label=f"{label}:", halign=Gtk.Align.END), 0, i, 1, 1)
            value_label = Gtk.Label(label=str(value))
            value_label.set_halign(Gtk.Align.START)
            value_label.add_css_class("monospace")
            grid.attach(value_label, 1, i, 1, 1)
        
        return grid

    def _create_hardware_info(self):
        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        
        cpu_info = SystemInfo.get_cpu_info()
        mem = SystemInfo.get_memory_info()
        
        rows = [
            ("处理器名称", SystemInfo.get_system_info()['processor']),
            ("物理核心", f"{cpu_info.get('cores', 0)}"),
            ("逻辑核心", f"{cpu_info.get('threads', 0)}"),
            ("当前频率", f"{cpu_info.get('current_freq', 0):.0f} MHz" if cpu_info.get('current_freq') else "未知"),
            ("最大频率", f"{cpu_info.get('max_freq', 0):.0f} MHz" if cpu_info.get('max_freq') else "未知"),
            ("内存总量", SystemInfo.format_bytes(mem['total'])),
            ("已用内存", SystemInfo.format_bytes(mem['used'])),
            ("可用内存", SystemInfo.format_bytes(mem['available'])),
            ("内存使用率", f"{mem['percent']:.1f}%"),
        ]
        
        for i, (label, value) in enumerate(rows):
            grid.attach(Gtk.Label(label=f"{label}:", halign=Gtk.Align.END), 0, i, 1, 1)
            value_label = Gtk.Label(label=str(value))
            value_label.set_halign(Gtk.Align.START)
            value_label.add_css_class("monospace")
            grid.attach(value_label, 1, i, 1, 1)
        
        return grid


class ProcessManagerPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="进程管理")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        search_entry = Gtk.Entry()
        search_entry.set_placeholder_text("搜索进程...")
        search_entry.set_size_request(200, -1)
        toolbar.append(search_entry)
        
        refresh_btn = Gtk.Button(label="🔄 刷新")
        refresh_btn.connect("clicked", self.on_refresh)
        toolbar.append(refresh_btn)
        
        kill_btn = Gtk.Button(label="🔴 结束进程")
        kill_btn.connect("clicked", self.on_kill)
        kill_btn.set_sensitive(False)
        toolbar.append(kill_btn)
        
        self.append(toolbar)
        
        self.store = Gtk.ListStore(str, int, float, float, str, str)
        
        treeview = Gtk.TreeView(model=self.store)
        
        columns = [
            ("进程名称", 0),
            ("PID", 1),
            ("CPU%", 2),
            ("内存(MB)", 3),
            ("状态", 4),
            ("用户名", 5),
        ]
        
        for i, (title, index) in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            treeview.append_column(column)
        
        self.treeview = treeview
        self.treeview.get_selection().connect("changed", self.on_selection_changed)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(treeview)
        scroll.set_size_request(-1, 400)
        
        self.append(scroll)
        
        self.kill_btn = kill_btn
        self.on_refresh(None)
        GLib.timeout_add(3000, self._auto_refresh)

    def on_refresh(self, widget):
        self.store.clear()
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status', 'username']):
            try:
                mem_mb = proc.info['memory_info'].rss / (1024 ** 2)
                self.store.append([
                    proc.info['name'],
                    proc.info['pid'],
                    proc.info['cpu_percent'],
                    round(mem_mb, 2),
                    proc.info['status'],
                    proc.info['username'] or ''
                ])
            except:
                continue

    def _auto_refresh(self):
        if self.treeview.get_realized():
            self.on_refresh(None)
        return True

    def on_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        self.kill_btn.set_sensitive(treeiter is not None)

    def on_kill(self, widget):
        model, treeiter = self.treeview.get_selection().get_selected()
        if treeiter:
            pid = model[treeiter][1]
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                self.on_refresh(None)
            except Exception as e:
                print(f"Error killing process: {e}")


class DiskCleanupPanel(Gtk.Box):
    def __init__(self, parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent = parent
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="磁盘清理")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        disk_list = Gtk.ListBox()
        
        for disk in SystemInfo.get_all_disks():
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            row.set_margin_start(10)
            row.set_margin_end(10)
            row.set_margin_top(5)
            row.set_margin_bottom(5)
            
            info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            info_box.append(Gtk.Label(label=f"{disk['device']} - {disk['mountpoint']}"))
            info_box.append(Gtk.Label(label=f"已用: {disk['percent']:.1f}% ({SystemInfo.format_bytes(disk['used'])} / {SystemInfo.format_bytes(disk['total'])})"))
            
            bar = Gtk.ProgressBar()
            bar.set_fraction(disk['percent'] / 100)
            bar.set_size_request(200, 16)
            
            row.append(info_box)
            row.append(bar)
            disk_list.append(row)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(disk_list)
        scroll.set_size_request(-1, 200)
        
        self.append(scroll)
        
        cleanup_btn = Gtk.Button(label="AI清理磁盘")
        cleanup_btn.set_size_request(150, 40)
        cleanup_btn.connect("clicked", self.on_cleanup)
        
        self.append(cleanup_btn)

    def on_cleanup(self, widget):
        self.parent.set_status("AI正在清理磁盘...")
        AIManager.clean_disk(self.parent.on_aim_result, self.parent.log_operation)


class StartupPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="启动项")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        refresh_btn = Gtk.Button(label="🔄 刷新")
        toolbar.append(refresh_btn)
        
        enable_btn = Gtk.Button(label="启用")
        enable_btn.set_sensitive(False)
        toolbar.append(enable_btn)
        
        disable_btn = Gtk.Button(label="禁用")
        disable_btn.set_sensitive(False)
        toolbar.append(disable_btn)
        
        add_btn = Gtk.Button(label="添加启动项")
        toolbar.append(add_btn)
        
        delete_btn = Gtk.Button(label="删除")
        delete_btn.set_sensitive(False)
        toolbar.append(delete_btn)
        
        self.append(toolbar)
        
        self.store = Gtk.ListStore(str, str, str, str)
        
        treeview = Gtk.TreeView(model=self.store)
        
        columns = [
            ("启动项名称", 0),
            ("路径", 1),
            ("状态", 2),
            ("来源", 3),
        ]
        
        for i, (title, index) in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            treeview.append_column(column)
        
        self.treeview = treeview
        self.treeview.get_selection().connect("changed", self.on_selection_changed)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(treeview)
        scroll.set_size_request(-1, 400)
        
        self.append(scroll)
        
        self.enable_btn = enable_btn
        self.disable_btn = disable_btn
        self.delete_btn = delete_btn
        
        self._load_startup_items()

    def _load_startup_items(self):
        self.store.clear()
        
        items = [
            ("AI电脑管家", "/home/show/mgr/main.py", "已启用", "用户"),
            ("终端", "/usr/bin/gnome-terminal", "已启用", "系统"),
            ("文件管理器", "/usr/bin/nautilus", "已禁用", "用户"),
            ("浏览器", "/usr/bin/firefox", "已启用", "用户"),
        ]
        
        for name, path, status, source in items:
            self.store.append([name, path, status, source])

    def on_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        has_selection = treeiter is not None
        self.enable_btn.set_sensitive(has_selection)
        self.disable_btn.set_sensitive(has_selection)
        self.delete_btn.set_sensitive(has_selection)


class NetworkMonitorPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="网络监控")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        stats_grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        
        self.download_speed_label = Gtk.Label(label="下载速度: --")
        self.upload_speed_label = Gtk.Label(label="上传速度: --")
        self.download_total_label = Gtk.Label(label="已下载: --")
        self.upload_total_label = Gtk.Label(label="已上传: --")
        
        stats_grid.attach(self.download_speed_label, 0, 0, 1, 1)
        stats_grid.attach(self.upload_speed_label, 1, 0, 1, 1)
        stats_grid.attach(self.download_total_label, 0, 1, 1, 1)
        stats_grid.attach(self.upload_total_label, 1, 1, 1, 1)
        
        self.append(stats_grid)
        
        network_info = SystemInfo.get_network_info()
        
        for interface, info in network_info.items():
            expander = Gtk.Expander(label=interface)
            
            grid = Gtk.Grid(column_spacing=20, row_spacing=8)
            
            grid.attach(Gtk.Label(label="状态:"), 0, 0, 1, 1)
            grid.attach(Gtk.Label(label="已连接" if info['status'] else "未连接"), 1, 0, 1, 1)
            
            grid.attach(Gtk.Label(label="速度:"), 0, 1, 1, 1)
            grid.attach(Gtk.Label(label=f"{info['speed']} Mbps" if info['speed'] else "未知"), 1, 1, 1, 1)
            
            grid.attach(Gtk.Label(label="IP地址:"), 0, 2, 1, 1)
            grid.attach(Gtk.Label(label=", ".join(info['addresses']) if info['addresses'] else "无"), 1, 2, 1, 1)
            
            expander.set_child(grid)
            self.append(expander)
        
        self.last_bytes = SystemInfo.get_network_io()
        GLib.timeout_add(1000, self._update_speed)

    def _update_speed(self):
        current = SystemInfo.get_network_io()
        download_speed = current.bytes_recv - self.last_bytes.bytes_recv
        upload_speed = current.bytes_sent - self.last_bytes.bytes_sent
        
        self.download_speed_label.set_label(f"下载速度: {SystemInfo.format_speed(download_speed)}")
        self.upload_speed_label.set_label(f"上传速度: {SystemInfo.format_speed(upload_speed)}")
        self.download_total_label.set_label(f"已下载: {SystemInfo.format_bytes(current.bytes_recv)}")
        self.upload_total_label.set_label(f"已上传: {SystemInfo.format_bytes(current.bytes_sent)}")
        
        self.last_bytes = current
        return True


class MemoryPanel(Gtk.Box):
    def __init__(self, parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent = parent
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="内存管理")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        self.mem_cards = Gtk.Grid(column_spacing=16, row_spacing=8)
        self.append(self.mem_cards)
        
        self.bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.bar_box.set_margin_top(10)
        self.append(self.bar_box)
        
        optimize_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        optimize_box.set_margin_top(10)
        
        release_btn = Gtk.Button(label="AI释放内存")
        release_btn.set_size_request(150, 40)
        release_btn.connect("clicked", self.on_release_memory)
        optimize_box.append(release_btn)
        
        self.append(optimize_box)
        
        high_mem_label = Gtk.Label(label="高内存进程")
        high_mem_label.add_css_class("heading")
        self.append(high_mem_label)
        
        self.store = Gtk.ListStore(str, int, float, float)
        
        treeview = Gtk.TreeView(model=self.store)
        
        columns = [
            ("进程名", 0),
            ("PID", 1),
            ("内存(MB)", 2),
            ("占比", 3),
        ]
        
        for i, (title, index) in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            treeview.append_column(column)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(treeview)
        scroll.set_size_request(-1, 200)
        
        self.append(scroll)
        
        self.connect("realize", self.on_realize)

    def on_realize(self, widget):
        self._update_memory_info()
        self._load_high_memory_processes()
        GLib.timeout_add(2000, self._update_memory_info)

    def _update_memory_info(self):
        while self.mem_cards.get_first_child():
            self.mem_cards.remove(self.mem_cards.get_first_child())
        
        while self.bar_box.get_first_child():
            self.bar_box.remove(self.bar_box.get_first_child())
        
        mem_info = SystemInfo.get_memory_info()
        
        total_mem = SystemInfo.format_bytes(mem_info['total'])
        used_mem = SystemInfo.format_bytes(mem_info['used'])
        available_mem = SystemInfo.format_bytes(mem_info['available'])
        cached_mem = SystemInfo.format_bytes(mem_info['cached'])
        
        cards = [
            ("总内存", total_mem, "#3498db"),
            ("已使用", used_mem, "#e74c3c"),
            ("可用", available_mem, "#2ecc71"),
            ("缓存", cached_mem, "#f39c12"),
        ]
        
        for i, (label, value, color) in enumerate(cards):
            card = self._create_mem_card(label, value, color)
            self.mem_cards.attach(card, i % 2, i // 2, 1, 1)
        
        bar_label = Gtk.Label(label=f"内存使用: {mem_info['percent']:.1f}%")
        bar_label.set_halign(Gtk.Align.START)
        
        bar = Gtk.ProgressBar()
        bar.set_fraction(mem_info['percent'] / 100)
        bar.set_size_request(-1, 24)
        
        self.bar_box.append(bar_label)
        self.bar_box.append(bar)
        
        return True

    def _create_mem_card(self, label, value, color):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        
        label_widget = Gtk.Label(label=label)
        value_widget = Gtk.Label(label=value)
        value_widget.set_css_classes(["title"])
        
        css = f"label.title {{ color: {color}; }}"
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        value_widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        
        box.append(label_widget)
        box.append(value_widget)
        
        return box

    def _load_high_memory_processes(self):
        self.store.clear()
        for proc in SystemInfo.get_high_memory_processes(10):
            mem_mb = proc['memory'] / (1024 ** 2)
            self.store.append([
                proc['name'],
                proc['pid'],
                round(mem_mb, 2),
                round(proc['percent'], 2)
            ])

    def on_release_memory(self, widget):
        self.parent.set_status("AI正在释放内存...")
        AIManager.run_aim_command('run', ['释放系统内存，清理缓存，关闭无用进程'], self.parent.on_aim_result, self.parent.log_operation)


class InterfacePanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="界面")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        themes = ["浅色主题", "深色主题", "系统主题"]
        font_sizes = ["小", "中", "大"]
        
        theme_label = Gtk.Label(label="主题")
        theme_combo = Gtk.ComboBoxText()
        for theme in themes:
            theme_combo.append_text(theme)
        theme_combo.set_active(0)
        
        font_label = Gtk.Label(label="字体大小")
        font_combo = Gtk.ComboBoxText()
        for size in font_sizes:
            font_combo.append_text(size)
        font_combo.set_active(1)
        
        grid = Gtk.Grid(column_spacing=20, row_spacing=10)
        grid.attach(theme_label, 0, 0, 1, 1)
        grid.attach(theme_combo, 1, 0, 1, 1)
        grid.attach(font_label, 0, 1, 1, 1)
        grid.attach(font_combo, 1, 1, 1, 1)
        
        self.append(grid)


class AIModelPanel(Gtk.Box):
    def __init__(self, parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent = parent
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="AI模型")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        self.store = Gtk.ListStore(str, str, str)
        
        treeview = Gtk.TreeView(model=self.store)
        
        columns = [
            ("模型名称", 0),
            ("模型ID", 1),
            ("大小", 2),
        ]
        
        for i, (title, index) in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            treeview.append_column(column)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(treeview)
        scroll.set_size_request(-1, 300)
        
        self.append(scroll)
        
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        refresh_btn = Gtk.Button(label="刷新模型列表")
        refresh_btn.connect("clicked", self.on_refresh)
        btn_box.append(refresh_btn)
        
        pull_btn = Gtk.Button(label="拉取模型")
        pull_btn.connect("clicked", self.on_pull_model)
        btn_box.append(pull_btn)
        
        delete_btn = Gtk.Button(label="删除模型")
        delete_btn.connect("clicked", self.on_delete_model)
        btn_box.append(delete_btn)
        
        self.append(btn_box)
        
        self.on_refresh(None)

    def on_refresh(self, widget):
        self.parent.set_status("正在获取Ollama模型列表...")
        AIManager.get_ai_models(self.on_models_received, self.parent.log_operation)

    def on_models_received(self, output):
        self.store.clear()
        
        lines = output.strip().split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('NAME') and not line.startswith('----'):
                parts = line.split()
                if len(parts) >= 2:
                    name = parts[0]
                    model_id = parts[1] if len(parts) > 1 else ''
                    size = parts[2] if len(parts) > 2 else ''
                    self.store.append([name, model_id, size])
        
        self.parent.set_status("就绪")

    def on_pull_model(self, widget):
        dialog = Gtk.Dialog(title="拉取模型", transient_for=self.parent)
        
        box = dialog.get_content_area()
        box.set_spacing(10)
        
        label = Gtk.Label(label="请输入模型名称（如 llama3, qwen2, gemma）:")
        box.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("例如：llama3")
        box.append(entry)
        
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("拉取", Gtk.ResponseType.OK)
        
        dialog.show()
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            model_name = entry.get_text().strip()
            if model_name:
                self.parent.set_status(f"正在拉取模型 {model_name}...")
                AIManager.ollama_pull(model_name, self.on_pull_result, self.parent.log_operation)
        
        dialog.destroy()

    def on_pull_result(self, output):
        self.parent.set_status("拉取完成")
        self.on_refresh(None)

    def on_delete_model(self, widget):
        dialog = Gtk.Dialog(title="删除模型", transient_for=self.parent)
        
        box = dialog.get_content_area()
        box.set_spacing(10)
        
        label = Gtk.Label(label="请输入要删除的模型名称:")
        box.append(label)
        
        entry = Gtk.Entry()
        box.append(entry)
        
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("删除", Gtk.ResponseType.OK)
        
        dialog.show()
        response = dialog.run()
        
        if response == Gtk.ResponseType.OK:
            model_name = entry.get_text().strip()
            if model_name:
                confirm_dialog = Gtk.Dialog(title="确认删除", transient_for=self.parent)
                confirm_box = confirm_dialog.get_content_area()
                confirm_box.append(Gtk.Label(label=f"确定要删除模型 {model_name} 吗？"))
                confirm_dialog.add_button("取消", Gtk.ResponseType.CANCEL)
                confirm_dialog.add_button("确定", Gtk.ResponseType.OK)
                confirm_dialog.show()
                confirm_response = confirm_dialog.run()
                
                if confirm_response == Gtk.ResponseType.OK:
                    self.parent.set_status(f"正在删除模型 {model_name}...")
                    AIManager.ollama_delete(model_name, self.on_delete_result, self.parent.log_operation)
                
                confirm_dialog.destroy()
        
        dialog.destroy()

    def on_delete_result(self, output):
        self.parent.set_status("删除完成")
        self.on_refresh(None)


class ToolboxPanel(Gtk.Box):
    def __init__(self, parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent = parent
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="工具箱")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        tools = [
            ("打开终端", self.open_terminal),
            ("打开文件管理器", self.open_file_manager),
            ("打开浏览器", self.open_browser),
            ("系统设置", self.open_settings),
            ("系统监视器", self.open_monitor),
        ]
        
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        
        for i, (label, callback) in enumerate(tools):
            btn = Gtk.Button(label=label)
            btn.set_size_request(160, 40)
            btn.connect("clicked", callback)
            row = i // 2
            col = i % 2
            grid.attach(btn, col, row, 1, 1)
        
        self.append(grid)

    def open_terminal(self, widget):
        subprocess.Popen(['gnome-terminal'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_file_manager(self, widget):
        subprocess.Popen(['nautilus'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_browser(self, widget):
        subprocess.Popen(['firefox'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_settings(self, widget):
        subprocess.Popen(['gnome-control-center'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_monitor(self, widget):
        subprocess.Popen(['gnome-system-monitor'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class AIFunctionsPanel(Gtk.Box):
    def __init__(self, parent):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.parent = parent
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        self.set_hexpand(True)
        self.set_vexpand(True)
        
        title_label = Gtk.Label(label="AI智能功能")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        ai_functions = [
            ("AI系统优化", AIManager.ai_system_optimize),
            ("AI故障诊断", AIManager.ai_fault_diagnosis),
            ("AI性能分析", AIManager.ai_performance_analysis),
            ("AI安全扫描", AIManager.ai_security_scan),
            ("AI驱动更新", AIManager.ai_drive_update),
            ("AI软件管理", AIManager.ai_software_management),
            ("AI网络优化", AIManager.ai_network_optimize),
            ("AI磁盘整理", AIManager.ai_disk_defragment),
            ("AI启动优化", AIManager.ai_startup_optimize),
            ("AI问题解答", self.on_question_answer),
        ]
        
        buttons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        buttons_box.set_hexpand(True)
        
        for label, callback in ai_functions:
            btn = Gtk.Button(label=label)
            btn.set_size_request(-1, 40)
            btn.set_hexpand(True)
            btn.set_halign(Gtk.Align.FILL)
            btn.connect("clicked", self._on_function_clicked, callback)
            buttons_box.append(btn)
        
        buttons_scroll = Gtk.ScrolledWindow()
        buttons_scroll.set_child(buttons_box)
        buttons_scroll.set_size_request(-1, 320)
        buttons_scroll.set_hexpand(True)
        
        self.append(buttons_scroll)
        
        output_label = Gtk.Label(label="实时输出")
        output_label.add_css_class("heading")
        self.append(output_label)
        
        self.output_view = Gtk.TextView()
        self.output_view.set_editable(False)
        self.output_view.set_wrap_mode(Gtk.WrapMode.WORD)
        self.output_view.set_cursor_visible(False)
        self.output_view.add_css_class("monospace")
        
        output_scroll = Gtk.ScrolledWindow()
        output_scroll.set_child(self.output_view)
        output_scroll.set_hexpand(True)
        output_scroll.set_vexpand(True)
        output_scroll.set_size_request(-1, 200)
        
        self.append(output_scroll)
        
        self.question_entry = None

    def _append_output(self, text):
        buffer = self.output_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, text + "\n")
        mark = buffer.create_mark(None, buffer.get_end_iter(), True)
        self.output_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def _clear_output(self):
        buffer = self.output_view.get_buffer()
        buffer.set_text("")

    def on_question_answer(self):
        pass

    def _make_log_callback(self):
        def log_callback(message):
            self._append_output(message)
            GLib.idle_add(self.parent.log_operation, message)
        return log_callback

    def _make_result_callback(self):
        def result_callback(output):
            self._append_output(f"\n[完成] {output}")
            self.parent.set_status("操作完成")
            GLib.idle_add(self.parent.log_operation, f"AI结果: {output[:200]}...")
        return result_callback

    def _on_function_clicked(self, button, callback):
        if callback == self.on_question_answer:
            self._show_question_dialog()
        else:
            self._clear_output()
            self.parent.set_status("AI正在执行操作...")
            self._append_output("[开始] 正在执行，请稍候...")
            callback(self._make_result_callback(), self._make_log_callback())

    def _show_question_dialog(self):
        dialog = Gtk.Dialog(title="AI智能问答", transient_for=self.parent)
        
        box = dialog.get_content_area()
        box.set_spacing(10)
        
        label = Gtk.Label(label="请输入您的问题:")
        box.append(label)
        
        entry = Gtk.Entry()
        entry.set_placeholder_text("例如：如何优化系统性能？")
        entry.set_size_request(300, -1)
        box.append(entry)
        
        dialog.add_button("取消", Gtk.ResponseType.CANCEL)
        dialog.add_button("提问", Gtk.ResponseType.OK)
        
        dialog.connect("response", self._on_question_response, entry)
        dialog.show()

    def _on_question_response(self, dialog, response, entry):
        if response == Gtk.ResponseType.OK:
            question = entry.get_text().strip()
            if question:
                self.parent.set_status("AI正在回答问题...")
                AIManager.ai_question_answer(question, self.parent.on_aim_result, self.parent.log_operation)
        dialog.destroy()


class LogOutputPanel(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.set_margin_start(20)
        self.set_margin_end(20)
        self.set_margin_top(20)
        
        title_label = Gtk.Label(label="操作日志")
        title_label.add_css_class("heading")
        self.append(title_label)
        
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        clear_btn = Gtk.Button(label="🗑️ 清空")
        clear_btn.connect("clicked", self.on_clear)
        toolbar.append(clear_btn)
        
        save_btn = Gtk.Button(label="💾 保存")
        save_btn.connect("clicked", self.on_save)
        toolbar.append(save_btn)
        
        self.append(toolbar)
        
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_wrap_mode(Gtk.WrapMode.WORD)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_child(self.log_view)
        scroll.set_size_request(-1, 200)
        
        self.append(scroll)

    def add_log(self, message):
        buffer = self.log_view.get_buffer()
        end_iter = buffer.get_end_iter()
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        buffer.insert(end_iter, log_entry)
        
        mark = buffer.create_mark(None, buffer.get_end_iter(), True)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)

    def on_clear(self, widget):
        buffer = self.log_view.get_buffer()
        buffer.set_text("")

    def on_save(self, widget):
        buffer = self.log_view.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        
        filename = f"ai_pc_manager_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(text)


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="AI电脑管家")
        
        self.set_default_size(1100, 750)
        self.set_resizable(True)
        
        main_layout = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(180, -1)
        sidebar.add_css_class("sidebar")
        
        sidebar_css = """
        .sidebar {
            background-color: #f8f9fa;
            border-right: 1px solid #dee2e6;
        }
        .sidebar button {
            padding: 12px 16px;
            font-size: 14px;
            color: #495057;
            border: none;
            border-radius: 0;
            margin: 2px 8px;
        }
        .sidebar button:hover {
            background-color: #e9ecef;
            border-radius: 4px;
        }
        .sidebar button.active {
            background-color: #007bff;
            color: white;
            border-radius: 4px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(sidebar_css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        
        menu_items = [
            ("首页概览", DashboardPanel),
            ("系统信息", SystemInfoPanel),
            ("进程管理", ProcessManagerPanel),
            ("磁盘清理", DiskCleanupPanel),
            ("启动项", StartupPanel),
            ("网络监控", NetworkMonitorPanel),
            ("内存", MemoryPanel),
            ("AI功能", AIFunctionsPanel),
            ("界面", InterfacePanel),
            ("AI模型", AIModelPanel),
            ("工具箱", ToolboxPanel),
            ("操作日志", LogOutputPanel),
        ]
        
        self.menu_buttons = []
        
        for label, panel_class in menu_items:
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self.on_menu_click, panel_class)
            sidebar.append(btn)
            self.menu_buttons.append(btn)
        
        self.content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.content_area.set_hexpand(True)
        
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        toolbar.set_margin_start(10)
        toolbar.set_margin_end(10)
        toolbar.set_margin_top(5)
        toolbar.set_margin_bottom(5)
        
        self.status_label = Gtk.Label(label="就绪")
        self.status_label.set_halign(Gtk.Align.END)
        
        toolbar.append(Gtk.Label())
        toolbar.append(self.status_label)
        
        self.content_area.append(toolbar)
        
        self.current_panel = None
        self.panel_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.panel_container.set_hexpand(True)
        self.panel_container.set_vexpand(True)
        self.content_area.append(self.panel_container)
        
        main_layout.append(sidebar)
        main_layout.append(self.content_area)
        
        self.set_child(main_layout)
        
        self._apply_styling()
        
        self.log_panel = None
        self.on_menu_click(self.menu_buttons[0], DashboardPanel)

    def _apply_styling(self):
        css = """
        window {
            background-color: #ffffff;
        }
        label.heading {
            font-size: 18px;
            font-weight: bold;
            color: #212529;
        }
        label.title {
            font-size: 24px;
            font-weight: bold;
            color: #212529;
        }
        label.small {
            font-size: 11px;
            color: #6c757d;
        }
        label.monospace {
            font-family: monospace;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def on_menu_click(self, button, panel_class):
        for btn in self.menu_buttons:
            btn.remove_css_class("active")
        button.add_css_class("active")
        
        if self.current_panel:
            self.panel_container.remove(self.current_panel)
        
        if panel_class in [DiskCleanupPanel, MemoryPanel, AIModelPanel, ToolboxPanel, AIFunctionsPanel]:
            self.current_panel = panel_class(self)
        else:
            self.current_panel = panel_class()
        
        if panel_class == LogOutputPanel:
            self.log_panel = self.current_panel
        
        self.panel_container.append(self.current_panel)

    def set_status(self, status):
        self.status_label.set_label(status)

    def log_operation(self, message):
        if self.log_panel:
            self.log_panel.add_log(message)
        else:
            print(message)

    def on_aim_result(self, result):
        self.set_status("操作完成")
        if self.log_panel:
            self.log_panel.add_log(f"AI结果: {result[:200]}...")


class AIApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.aipc.manager")
        self.window = None
    
    def do_activate(self):
        if not self.window:
            self.window = MainWindow(self)
        self.window.present()


def main():
    app = AIApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

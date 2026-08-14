package system

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
)

type HardwareInfo struct {
	Hostname     string `json:"hostname"`
	OS           string `json:"os"`
	Kernel       string `json:"kernel"`
	CPU          string `json:"cpu"`
	Memory       string `json:"memory"`
	Architecture string `json:"architecture"`
}

func GetHardwareInfo() (*HardwareInfo, error) {
	info := &HardwareInfo{
		Architecture: runtime.GOARCH,
		OS:           runtime.GOOS,
	}

	hostname, err := os.Hostname()
	if err == nil {
		info.Hostname = hostname
	}

	kernel, err := exec.Command("uname", "-r").Output()
	if err == nil {
		info.Kernel = strings.TrimSpace(string(kernel))
	}

	cpu, err := exec.Command("sh", "-c", "grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2").Output()
	if err == nil {
		info.CPU = strings.TrimSpace(string(cpu))
	}

	mem, err := exec.Command("sh", "-c", "free -h | grep Mem | awk '{print $2}'").Output()
	if err == nil {
		info.Memory = strings.TrimSpace(string(mem))
	}

	return info, nil
}

func ExecCommand(cmd string, args ...string) (string, error) {
	c := exec.Command(cmd, args...)
	output, err := c.CombinedOutput()
	return string(output), err
}

func ExecCommandWithInput(input string, cmd string, args ...string) (string, error) {
	c := exec.Command(cmd, args...)
	c.Stdin = strings.NewReader(input)
	output, err := c.CombinedOutput()
	return string(output), err
}

type ProcessInfo struct {
	PID  int    `json:"pid"`
	Name string `json:"name"`
	CPU  string `json:"cpu"`
	MEM  string `json:"mem"`
}

func ListProcesses() ([]ProcessInfo, error) {
	output, err := exec.Command("ps", "aux", "--no-headers").Output()
	if err != nil {
		return nil, err
	}
	lines := strings.Split(strings.TrimSpace(string(output)), "\n")
	var processes []ProcessInfo
	for _, line := range lines {
		fields := strings.Fields(line)
		if len(fields) >= 11 {
			processes = append(processes, ProcessInfo{
				PID:  parseInt(fields[1]),
				Name: fields[10],
				CPU:  fields[2],
				MEM:  fields[3],
			})
		}
	}
	return processes, nil
}

func parseInt(s string) int {
	var n int
	fmt.Sscanf(s, "%d", &n)
	return n
}

func KillProcess(pid int) error {
	proc, err := os.FindProcess(pid)
	if err != nil {
		return err
	}
	return proc.Kill()
}

type VMInterface struct{}

func NewVMInterface() *VMInterface {
	return &VMInterface{}
}

func (v *VMInterface) ListVMs() ([]string, error) {
	output, err := exec.Command("virsh", "list", "--all", "--name").Output()
	if err != nil {
		gnomeBoxes, err2 := exec.Command("ls", "/var/lib/gnome-boxes/").Output()
		if err2 != nil {
			return nil, fmt.Errorf("no VM manager found: virsh or gnome-boxes")
		}
		return strings.Fields(string(gnomeBoxes)), nil
	}
	return strings.Fields(string(output)), nil
}

func (v *VMInterface) StartVM(name string) error {
	return exec.Command("virsh", "start", name).Run()
}

func (v *VMInterface) StopVM(name string) error {
	return exec.Command("virsh", "destroy", name).Run()
}

func (v *VMInterface) VMStatus(name string) (string, error) {
	output, err := exec.Command("virsh", "domstate", name).Output()
	if err != nil {
		return "unknown", err
	}
	return strings.TrimSpace(string(output)), nil
}

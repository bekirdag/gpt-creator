package main

import (
	"bufio"
	"os"
	"os/exec"
	"sync"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/creack/pty"
)

type jobRequest struct {
	title    string
	dir      string
	command  string
	args     []string
	env      []string
	onStart  func()
	onFinish func(error)
}

type jobManager struct {
	queue   []jobRequest
	current *jobRequest
	running bool
}

func newJobManager() *jobManager {
	return &jobManager{}
}

func (jm *jobManager) Enqueue(req jobRequest) tea.Cmd {
	jm.queue = append(jm.queue, req)
	return jm.nextCmd()
}

func (jm *jobManager) Handle(msg jobMsg) tea.Cmd {
	switch msg := msg.(type) {
	case jobStartedMsg:
		if jm.current != nil && jm.current.onStart != nil {
			jm.current.onStart()
		}
	case jobFinishedMsg:
		if jm.current != nil && jm.current.onFinish != nil {
			jm.current.onFinish(msg.Err)
		}
		jm.running = false
		jm.current = nil
		return jm.nextCmd()
	case jobChannelClosedMsg:
		jm.running = false
		jm.current = nil
		return jm.nextCmd()
	}
	return nil
}

func (jm *jobManager) nextCmd() tea.Cmd {
	if jm.running {
		return nil
	}
	if len(jm.queue) == 0 {
		return nil
	}
	req := jm.queue[0]
	jm.queue = jm.queue[1:]
	jm.current = &req
	jm.running = true

	ch := make(chan jobMsg)
	go runJob(req, ch)
	return waitForJobMsg(ch)
}

func runJob(req jobRequest, ch chan<- jobMsg) {
	defer close(ch)

	ch <- jobStartedMsg{Title: req.title}

	cmd := exec.Command(req.command, req.args...)
	if req.dir != "" {
		cmd.Dir = req.dir
	}
	if len(req.env) > 0 {
		env := append([]string{}, os.Environ()...)
		env = append(env, req.env...)
		cmd.Env = env
	}

	ptmx, err := pty.Start(cmd)
	if err != nil {
		ch <- jobLogMsg{Title: req.title, Line: err.Error()}
		ch <- jobFinishedMsg{Title: req.title, Err: err}
		return
	}
	defer ptmx.Close()

	wg := sync.WaitGroup{}
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(ptmx)
		for scanner.Scan() {
			ch <- jobLogMsg{Title: req.title, Line: scanner.Text()}
		}
	}()

	wg.Wait()
	err = cmd.Wait()
	ch <- jobFinishedMsg{Title: req.title, Err: err}
}

func waitForJobMsg(ch <-chan jobMsg) tea.Cmd {
	return func() tea.Msg {
		msg, ok := <-ch
		if !ok {
			return jobChannelClosedMsg{}
		}
		return msg
	}
}

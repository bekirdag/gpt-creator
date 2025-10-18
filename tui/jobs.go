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
	maxParallel int
	nextID      int
	queue       []*jobState
	running     map[int]*jobState
}

type jobState struct {
	id         int
	req        jobRequest
	ch         chan jobMsg
	cmd        *exec.Cmd
	mu         sync.Mutex
	cancelled  bool
	cancelOnce sync.Once
}

func newJobManager() *jobManager {
	return &jobManager{
		maxParallel: 1,
		running:     make(map[int]*jobState),
	}
}

func (jm *jobManager) Enqueue(req jobRequest) (int, tea.Cmd) {
	jm.nextID++
	state := &jobState{
		id:  jm.nextID,
		req: req,
	}
	jm.queue = append(jm.queue, state)
	return state.id, jm.startJobs()
}

func (jm *jobManager) Handle(msg jobMsg) tea.Cmd {
	id := msg.jobID()
	state, ok := jm.running[id]
	switch message := msg.(type) {
	case jobStartedMsg:
		if ok && state.req.onStart != nil {
			state.req.onStart()
		}
	case jobFinishedMsg:
		if ok && state.req.onFinish != nil {
			state.req.onFinish(message.Err)
		}
		delete(jm.running, id)
		return jm.startJobs()
	case jobChannelClosedMsg:
		delete(jm.running, id)
		return jm.startJobs()
	}
	return nil
}

func (jm *jobManager) startJobs() tea.Cmd {
	var cmds []tea.Cmd
	for len(jm.running) < jm.maxParallel && len(jm.queue) > 0 {
		state := jm.queue[0]
		jm.queue = jm.queue[1:]
		state.ch = make(chan jobMsg)
		jm.running[state.id] = state
		go runJob(state, state.ch)
		cmds = append(cmds, waitForJobMsg(state.id, state.ch))
	}
	if len(cmds) == 0 {
		return nil
	}
	return tea.Batch(cmds...)
}

func (jm *jobManager) SetMaxParallel(n int) tea.Cmd {
	if n < 1 {
		n = 1
	}
	if n == jm.maxParallel {
		return nil
	}
	jm.maxParallel = n
	return jm.startJobs()
}

func (jm *jobManager) Cancel(id int) (bool, tea.Cmd) {
	if state, ok := jm.running[id]; ok {
		state.cancelOnce.Do(func() {
			state.mu.Lock()
			state.cancelled = true
			cmd := state.cmd
			state.mu.Unlock()
			if cmd != nil && cmd.Process != nil {
				_ = cmd.Process.Signal(os.Interrupt)
			}
		})
		return true, nil
	}
	for idx, state := range jm.queue {
		if state.id != id {
			continue
		}
		jm.queue = append(jm.queue[:idx], jm.queue[idx+1:]...)
		cancelMsg := func() tea.Msg { return jobCancelledMsg{ID: state.id, Title: state.req.title} }
		startCmd := jm.startJobs()
		if startCmd != nil {
			return true, tea.Batch(cancelMsg, startCmd)
		}
		return true, cancelMsg
	}
	return false, nil
}

func runJob(state *jobState, ch chan<- jobMsg) {
	defer close(ch)

	req := state.req
	ch <- jobStartedMsg{Title: req.title, ID: state.id}

	cmd := exec.Command(req.command, req.args...)
	if req.dir != "" {
		cmd.Dir = req.dir
	}
	if len(req.env) > 0 {
		env := append([]string{}, os.Environ()...)
		env = append(env, req.env...)
		cmd.Env = env
	}

	state.mu.Lock()
	state.cmd = cmd
	state.mu.Unlock()

	ptmx, err := pty.Start(cmd)
	if err != nil {
		ch <- jobLogMsg{Title: req.title, Line: err.Error(), ID: state.id}
		ch <- jobFinishedMsg{Title: req.title, Err: err, ID: state.id}
		return
	}
	defer ptmx.Close()

	wg := sync.WaitGroup{}
	wg.Add(1)
	go func() {
		defer wg.Done()
		scanner := bufio.NewScanner(ptmx)
		for scanner.Scan() {
			ch <- jobLogMsg{Title: req.title, Line: scanner.Text(), ID: state.id}
		}
	}()

	wg.Wait()
	err = cmd.Wait()
	ch <- jobFinishedMsg{Title: req.title, Err: err, ID: state.id}
}

func waitForJobMsg(id int, ch <-chan jobMsg) tea.Cmd {
	return func() tea.Msg {
		msg, ok := <-ch
		if !ok {
			return jobChannelClosedMsg{ID: id}
		}
		return msg
	}
}

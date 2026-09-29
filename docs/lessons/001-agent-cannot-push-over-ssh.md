# The agent cannot push over SSH

## What happened

Claude Code could commit but every push failed:

    SSH_AUTH_SOCK=unset
    Could not open a connection to your authentication agent.
    git@github.com: Permission denied (publickey).

Running `ssh-add` in my terminal first did not help. Launching Claude Code
after loading the key did not help either.

## Why

Claude Code runs bash commands in a subshell that does not inherit
`SSH_AUTH_SOCK` from the terminal it was launched from. With no agent socket,
git has no key to offer GitHub, and there is no way for the agent to prompt
for a passphrase.

The usual `ssh-agent` bootstrap in `~/.bashrc` does not close the gap either,
because that block only fires for interactive shells. The agent's shell is not
interactive.

This is correct behavior, not a bug. An agent that could silently reach an
unlocked SSH key would be a worse tool.

## What I changed

Nothing. I kept the SSH remote and accepted the split:

- Agent: commits, issue creation, labels, code
- Me: `git push`

The alternative was switching the remote to HTTPS and letting the `gh` CLI act
as a git credential helper, which makes agent pushes work. I declined it. Push
is the step where work leaves my machine, and I want a human at that boundary.

## What I'd do differently

Recognize the symptom faster. `SSH_AUTH_SOCK=unset` in the agent's environment
is the entire diagnosis and takes one command to confirm. I spent time trying
launch-order workarounds that could never have worked, because the problem is
structural rather than a race.

The general lesson: the agent's shell is not my shell. Anything my environment
provides through an interactive session, a desktop keyring, or a login hook is
not automatically available to it. Worth checking that assumption directly
rather than reasoning from what works when I type the command myself.

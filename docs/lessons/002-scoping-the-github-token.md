# Scoping the GitHub token

## What happened

The agent needs GitHub API access to create issues, read tickets, and apply
labels. The obvious way to provide it is the `gh` CLI's own login, which uses
a browser OAuth flow and requests a broad scope set including full `repo`
access across the account.

That works immediately and is the wrong default for an agent.

## Why

The agent reads text I do not control. Issue bodies, pull request comments,
READMEs of dependencies, anything it fetches. A crafted instruction inside
that text can attempt to get the agent to act. This is prompt injection, and
it is not solved by reading every permission prompt carefully, because the
prompt looks like the work I asked for.

The question to ask is not "will the agent be tricked." It is "what can be
reached if it is." With a broad account-level token, the answer includes every
repository on the account, public and private, plus the ability to create
gists and post comments, which are exfiltration paths.

Token storage is a side issue by comparison. The credential sits in a
mode-0600 file readable by any process running as me, which is a real
property, but it is not the thing that turns a malicious issue body into
damage. Scope is.

## What I changed

Replaced the broad OAuth login with a fine-grained personal access token.

A fine-grained PAT differs from a classic token in three ways that matter here:

- **Repository selection.** It is bound to specific repositories rather than
  everything the account can reach. A token for one repo cannot see the others.
- **Per-permission grants.** Instead of coarse scopes like `repo`, permissions
  are chosen individually: contents, issues, pull requests, and so on, each
  read-only or read-write. Everything not granted is denied.
- **Mandatory expiry.** The token stops working on a date I choose rather than
  living forever until I remember it exists.

For this repo the token grants only what the workflow actually needs:
repository contents, issues, and pull requests, on one repository, with
everything else off. No gist creation, no workflow access, no account-level
permissions.

The token is stored in a file readable only by my user, and injected into the
environment by a shell function that launches Claude Code. It exists in that
process and nowhere else. The broad `gh` login stays logged out.

Verification was the important part. Confirming the agent could still create
issues proved the grant was sufficient; confirming a gist creation attempt
failed proved the denial was real. A scoped credential nobody tested is an
assumption, not a control.

## What I'd do differently

Do this before connecting the agent to the tracker at all, not after.

The broad token was live for a day while I wired up the workflow. Nothing
happened, but the window existed because the easy path and the correct path
diverged and I took the easy one first.

The general lesson: when an agent needs a credential, the first question is
what the smallest working version of that credential looks like. Not whether
the agent can be trusted with more.

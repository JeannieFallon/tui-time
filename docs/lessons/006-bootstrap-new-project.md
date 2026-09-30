# Bootstrapping a new repo for Claude Code + skills

## What happened

The second time I set up a repo for this workflow, I couldn't remember the
order of operations and had to reconstruct it from an old conversation. The
steps aren't hard. There are just enough of them, spread across GitHub, my
shell, and Claude Code, that the sequence doesn't stick.

## Why

Setup touches three separate systems, and each has its own auth:

- GitHub, for the scoped token and the triage labels
- My shell, for storing the token and launching Claude Code with it
- Claude Code, for the skills configuration

The skills are installed globally, so they're already available in every repo.
Everything else is per-repo and has to be repeated.

## The procedure

Placeholders: `<project>` is a short name for the repo, `<launcher>` is the
shell function name for it.

**1. Clone the repo.**

**2. Create a fine-grained PAT scoped to this repo only.** Same permissions as
my other project tokens. Details in the machine-local notes, not here.

**3. Store the token.** File created at mode 600 before anything is written to
it; token read without echo and without landing in shell history.

    mkdir -p ~/.config/<project>
    install -m 600 /dev/null ~/.config/<project>/gh-token
    read -rs tok && printf '%s' "$tok" > ~/.config/<project>/gh-token && unset tok

The last line waits silently. Paste, press Enter.

The token is stored unencrypted, readable only by my user. That's deliberate,
and it's the same model `gh`, the AWS CLI, and Docker use for their own
credentials. Encrypting it at rest would add little: the launcher decrypts it
into the session environment anyway, where the agent can see it, and anyone
able to read files as my user could read it there too. The control that
matters is scope. The token reaches one repository, expires, and revokes in
one click. A leak is contained by what it can do, not by where it's kept.

**4. Add a launcher function to `~/.bashrc`.** One per repo. Copy an existing
one and change the name and the path.

    <launcher>() {
        GH_TOKEN="$(cat ~/.config/<project>/gh-token)" claude "$@"
    }

Then `source ~/.bashrc`.

**5. Create the triage labels.** The broad `gh` login stays logged out, so plain
`gh` has no credentials. Borrow the repo's token for the duration, from inside
the repo:

    export GH_TOKEN="$(cat ~/.config/<project>/gh-token)"
    gh label create needs-triage --color FBCA04
    gh label create needs-info --color D4C5F9
    gh label create ready-for-agent --color 0E8A16
    gh label create ready-for-human --color 1D76DB
    unset GH_TOKEN

`wontfix` exists on new repos by default. The setup skill records these label
names but does not create them, so this step is easy to miss and `/triage`
fails without it.

**6. Launch and configure.**

    <launcher>

Inside the session:

    /setup-matt-pocock-skills

Once per repo. Writes `docs/agents/` and an `## Agent skills` block in
`CLAUDE.md`. Commit that as its own commit.

**7. Start working.**

    /grill-with-docs

## What I'd do differently

Write this down the first time. The sequence was obvious while I was in it and
gone a week later.

One ordering note: the token and labels come before the setup skill, not after.
The skill assumes GitHub is already reachable and the labels already exist. It
won't fail loudly if they don't; the downstream skills will.

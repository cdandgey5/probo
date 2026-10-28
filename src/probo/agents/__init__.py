"""Reference agents for Harbor (roadmap package P2-A).

Run them with Harbor's ``module:Class`` syntax from the environment Probo is
installed in, for example::

    uv run harbor run -p <task> -a probo.agents.saboteur:Saboteur
    uv run probo run <task> -a probo.agents.command:CommandAgent \\
        --ak command='my-cli --prompt {instruction_file}'

* ``saboteur``: never fixes anything; edits or deletes tests, or disables
  the test task from a build script. Every run must be flagged ``tampered``.
* ``command``: runs any command-line agent inside the task container from a
  template, so a team can evaluate its own tool as a black box.
"""

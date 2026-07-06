# :bug: How to debug the application

The steps below describe how to set up interactive debugging with PyCharm or VSCode.

## PyCharm Debugging Setup
Update `k8s/base/app.configmap.yaml` with `data` field `PYTHONBREAKPOINT: "utils.pycharm_debugger"`

In PyCharm:

1. Go to 'Run' in the toolbar
2. Click on 'Edit Configurations'
3. Click on '+' in the top left of the dialog
4. Select 'Python Debug Server'
5. Set the host to 0.0.0.0 and the port to 6400, and the name as you see fit.
6. For 'path mappings' set /path/to/{{ copier__project_slug}}/backend=/app/src
7. Check 'Redirect console output to console'
8. Remove check on 'Suspend after connect'.
9. Click 'Ok'

![debug__debug_configuration.png](images/debug__debug_configuration.png)

## VSCode Debugging Setup

VSCode uses [debugpy](https://github.com/microsoft/debugpy) (already in `requirements/local.in`).
Unlike PyCharm, the pod runs the debug *server* and VSCode *attaches* to it, so Tilt
forwards the debug port (`5678`) into the pod for you.

1. Set `PYTHONBREAKPOINT: "{{ copier__project_slug }}.utils.vscode_debugger"` in the
   `data` field of `k8s/base/app.configmap.yaml`.
2. Run `tilt up`. Confirm the `backend` resource forwards both `8000` and `5678`.
3. A `.vscode/launch.json` with an "Attach to Django (debugpy in k8s)" configuration is
   already included at the project root.

## Debugging in development

`PYTHONBREAKPOINT` (set above) routes Python's built-in `breakpoint()` to the debugger for
your IDE. Before the code you want to inspect, add:

```python
breakpoint()
```

Then call the code as usual (e.g. hit the endpoint). What happens when `breakpoint()` is
reached differs by IDE:

### PyCharm

Hitting `breakpoint()` only *connects* the debugger — it does **not** suspend on that line
(`suspend=False`). You must set break points in the PyCharm gutter at the lines you want to
stop on; execution pauses when it reaches one of those.

### VSCode

`breakpoint()` **is** the stop point — you do not need to set gutter breakpoints:

1. Add `breakpoint()` and trigger the code. The request **blocks** at that line waiting for
   a debugger to attach (debugpy starts listening on the first `breakpoint()` that is hit).
2. In VSCode, open the Run and Debug panel and start "Attach to Django (debugpy in k8s)".
   Execution resumes and pauses right at your `breakpoint()`.

Once attached you *may* optionally set additional gutter breakpoints in VSCode and they'll be
hit on subsequent runs, but a plain `breakpoint()` is sufficient on its own.

> :warning: Because the request blocks until you attach, a `breakpoint()` you never attach
> to will hang that request indefinitely. This is dev-only (local readiness/liveness probes
> are disabled), but remember to remove `breakpoint()` and reset `PYTHONBREAKPOINT: ""` when done.

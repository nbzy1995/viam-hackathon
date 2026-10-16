# Reference projects

## Ringside voice interface

[Ringside](https://github.com/JoeyYu23/ringside), the team's AI × Finance
hackathon project, is included in `ringside/` as a Git submodule pinned to
`ddbecfad47d194b5fc163dde65d3d9325a56ba12`.

It supplies reference code for browser audio, transcripts, live status, and
voice interaction. It is not yet connected to the Viam robot.
See the [integration report](../docs/voice-ui-integration-report.md) for the
reuse map, proposed approach, and validation boundaries.

When cloning this project:

```sh
git clone --recurse-submodules https://github.com/nbzy1995/viam-hackathon.git
```

For an existing checkout:

```sh
git submodule update --init --recursive references/ringside
```

The original source and history remain in its upstream repository. No license
file was present at the pinned revision; retain attribution and establish reuse
rights before publishing adapted code. Credentials and local runtime data are
not part of this integration.

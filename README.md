# OpenStack MCP + Agent PoC

This repository contains the code and instructions to run an OpenStack MCP
server and a very basic agent companion program to test it.

The approach taken in this PoC is:

- Use the OpenStack `codegenerator` project (`openstack-code-generator`) to
  create OpenAPI Specs for OpenStack.

- Use the `mcp-openapi` project to start multiple MCP servers (one per
  OpenStack component) from a filtered version of their full OpenAPI
  specifications.

- Use the `agent` code to interact with the MCP servers via an LLM.

You don't need all this for a quick test, you can just follow the
[QuickStart](#quickstart) guide, but if you want to do something different
you'll need to go through the [Running things](./docs/running-things.md) guide.

## QuickStart

We assume you have access to an OpenStack deployment and to an LLM, as they are
required to run things.

You'll also need the `uv` package manager. If you don't you can install it with
`sudo dnf install uv`.

We'll be using 2 terminals, one for the MCP server and another for the Agent.

### Clone this repository

We'll clone this repository with just the minimum external projects necessary
to run things.

```bash
$ git clone --shallow-submodules \
  --recurse-submodules=mcp-openapi \
  https://github.com/Akrog/mcp-openstack.git

$ cd mcp-openstack
```

### Run the MCP server

First we need to configure the MCP server, and for that we'll edit the
`servers.yaml` file and replace the `<NOVA_PUBLIC_URL>`, `<CINDER_PUBLIC_URL>`,
and `<GLANCE_PUBLIC_URL>` placeholders with the values of our cluster.

You'll notice that only a subset of REST API paths are being enabled to avoid
having tool many tools that could go over our model's context window or induce
hallucinations.

Now we can run the server:

```bash
$ cd mcp-openapi

$ uv run main.py --config ../servers.yaml
```

We leave this service running on this terminal and go to another terminal.

### Run the Agent

In another terminal we'll go into the `agent` directory:

```bash
$ cd agent
```

#### OpenStack client config

Now we'll make sure the configuration for the OpenStack client is available in
one of the standard locations as [described in the
documentation](https://docs.openstack.org/python-openstackclient/pike/configuration/index.html#clouds-yaml):
- `agent/`
- `~/.config/openstack/`

If we are running an OSP 18 cloud we can get this with:

```bash
$ oc cp openstackclient:/home/cloud-admin/.config/openstack/clouds.yaml ./clouds.yaml
$ oc cp openstackclient:/home/cloud-admin/.config/openstack/secure.yaml ./secure.yaml 
```

#### LLM config

We'll create an `llm.token` file with the secret/token for the OpenAI LLM
endpoint we want to use.

Then edit the `agent.json` file to replace the `<LLM_URL>` placeholder with our
LLM's address and replace `<MODEL>` with the model we want to use. For example
for Anthropic we could have something like this:

```
{
  "base_url": "https://api.anthropic.com/v1",
  "model": "claude-3-5-haiku-20241022",
  < ... >
}
```

#### Run the agent

Now we just need to start the agent:

```bash
$ uv run main.py
```

### Enjoy

We can now ask things about our deployment and see the REST API calls on the
MCP server terminal.

For example to get the nova flavors we could do:

```
$ uv run main.py
LLM: claude-3-5-haiku-20241022 @ https://api.anthropic.com/v1 Tools: 46
>>> What are my flavors?
```

Be aware that the agent doesn't have memory, so each prompt will be a clean
prompt for the LLM.

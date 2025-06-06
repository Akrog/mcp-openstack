# Running things

If we divide the process into small steps we end up with the following 10 steps
to reproduce everything:

1. Clone this repo
2. Create OpenStack's OpenAPI specs using `code-generator`.
3. Filter only `GET` methods from the  OpenStack specs
4. Configure the MCP server
5. Run the MCP server
6. Get the OpenStack client configuration
7. Configure the LLM
8. Configure the Agent
9. Run the agent
10. Enjoy

We'll need to have `pip` and `tox` installed.

## 1. Clone this repo

To clone the repository and all the submodules in full we can run:

```bash
$ git clone \
  --recurse-submodules \
  https://github.com/Akrog/mcp-openstack.git

$ cd mcp-openstack
```

If we don't care too much about the git history in the submodules (which we
usually don't) we can add `--shallow-submodules` to the clone command like we
had in the QuickStart guide.

If we had already clone the repository using the QuickStart command we can now
just get the rest of the submodules with:

```bash
$ git submodule init
```

## 2. Create OpenAPI specs

### Virtual env

We start by creating a virtual environment for `codegenerator` and installing
the tool there and all the different OpenStack components, which are necessary
for the tool to generate their OpenAPI specs:

```bash
$ python -m venv openstack-code-generator/.venv

$ source openstack-code-generator/.venv/bin/activate

$ pip install -e openstack-code-codegenerator

$ for component in nova cinder glance placement; do
    pip install \
      -c https://releases.openstack.org/constraints/upper/master \
      -r openstack-components/${component}/requirements.txt

    pip install -e openstack-components/${component}
  done
```

### API-REF

To get a more detailed OpenAPI we need to create the `api-ref` documentation of
the different components.

We can do this with:

```bash
$ cd openstack-components

$ for component in nova cinder glance placement; do
    cd ${component}
    tox -e api-ref
    cd ..
  done
```

### Specs

Now we need to create the specs for all the components and save them in the
`openstack-openapi` working directory.

Nova:

```bash
$ openstack-codegenerator \
   --work-dir openstack-openapi \
   --target openapi-spec \
   --validate \
   --yaml-version 1.1 \
   --service-type compute \
   --api-ref-src openstack-components/nova/api-ref/build/html/index.html
```

Cinder:

```bash
$ openstack-codegenerator \
   --work-dir openstack-openapi \
   --target openapi-spec \
   --validate \
   --yaml-version 1.1 \
   --service-type block-storage \
   --api-ref-src openstack-components/cinder/api-ref/build/html/v3/index.html
```

Glance:

```bash
$ openstack-codegenerator \
   --work-dir openstack-openapi \
   --target openapi-spec \
   --validate \
   --yaml-version 1.1 \
   --service-type image \
   --api-ref-src openstack-components/glance/api-ref/build/html/v2/index.html
```

Placement:

```bash
$ openstack-codegenerator \
   --work-dir openstack-openapi \
   --target openapi-spec \
   --validate \
   --yaml-version 1.1 \
   --service-type placement \
   --api-ref-src openstack-components/placement/api-ref/build/html/index.html
```

Now we should have all our specs in `openstack-openapi/openapi_specs`, one
directory for each spec file.

## 3. Filter methods

We'll use the `slim-openapi` script to perform 2 things in our components
OpenAPI specs:
- Filter only `GET` methods
- Modify the OpenAPI specs so our parser can handle them

```bash
$ cd mcp-openapi

$ for component in compute,nova,v2 block-stroage,cinder,v3 image,glance,v2 plaemente,placement,v1; do IFS=","; set -- $component;
    SVC=$1; COMP=$2; V=$3
    echo "Generating $COMP"
    uv run scripts/slim-openapi  -f ../openstack-openapi/openapi_specs/$SVC/$V.yaml  --routes "/"  -v get  -o ../openstack-openapi/$COMP-get.yaml > /dev/null
  done

$ cd ..
```

If we want to have **all** the operations we can use `-v
get,patch,post,put,delete` instead of `-v get` in the above commands.

## 4. Configure MCP server

In the `servers.yaml` file we first need to replace `<NOVA_PUBLIC_URL>`,
`<CINDER_PUBLIC_URL>` and `<GLANCE_PUBLIC_URL>` with the public endpoints in
our OpenStack deployment.

We can also modify the `paths` section to have the paths from the OpenAPI spec
files we want to be presented as tools.  If we want to have them **all** we can
just use:

```YAML
servers:
  - paths:
    - /
```

You can also replace the `certificate` value with the location of your
OpenStack cafile if you have it.

You can also include placement as a new server using the other servers in that
file as reference.

We are using 3 configuration options together to make sure that the tool names
are unique among all the MCP servers and that they don't exceed the maximum
length that some LLM servers have. These options are: `name`, `use_prefix`, and
`tool_name_length`.

## 5. Run MCP server

Once we have everything ready running the server is straightforward:

```bash
$ uv run main.py --config ../servers.yaml
```

## 6. Get the OpenStack client configuration

The agent will take care of creating keystone tokens for the tool calls, so we need to have the OpenStack client configuration available for the agent.

As [described in the
documentation](https://docs.openstack.org/python-openstackclient/pike/configuration/index.html#clouds-yaml)
we can have its configuration in one of these 2 directories:
- `agent/`
- `~/.config/openstack/`

If we are running an OSP 18 cloud we can get this with:

```bash
$ oc cp openstackclient:/home/cloud-admin/.config/openstack/clouds.yaml ./agent/clouds.yaml
$ oc cp openstackclient:/home/cloud-admin/.config/openstack/secure.yaml ./agent/secure.yaml
```

## 7. Configure the LLM

The configuration of the LLM goes in `agent.json` file (or any file we like if
we use the `-c` option when calling `main.py`).

To be able to use the LLM the agent needs to know 3 things:
- The URL of the OpenAI compatible server ==> `base_url`
- The model ==> `model`
- The API key/token ==> `api_key`

There are 3 ways we can provide the API key to the agent:
- Directly in the `api_key` value
- In a file and then use the `open` directive
- In an environmental variable and then use the `os.environ` directive

For example for Anthropic using a local file for the key:

```
{
  "base_url": "https://api.anthropic.com/v1",
  "model": "claude-3-5-haiku-20241022",
  "api_key": "open/llm.token",
  < ... >
}
```

For example using a local LiteLLM server with the key in an environmental
variable:

```
{
  "base_url": "http://litellm.local:4000",
  "model": "openai/qwen3:8b",
  "api_key": "os.environ/LITELLM_API_KEY",
  < ... >
}
```

## 8. Configure the Agent

Once we have configured the LLM we still need to configure the MCP servers that
the agent needs to use in the `agent.json` file.

Right now only `sse` MCP servers are supported, and the default `agent.json`
file included in the repository already has nova, cinder, and glance
configured.

If you have added placement to the MCP server, then you may want to add as the
first element of `servers`:

```JSON
  {
    "type": "sse",
    "config": {
      "url": "http://localhost:8000/block-storage/sse",
      "timeout": 20
    }
  },
```

## 9. Run the agent

Just like with the MCP server, running the agent is straightforward.

```bash
$ uv run main.py
```

The agent has 3 command line configuration options:

- `-v` ==> To enable verbose mode. It can be provided multiple times: `-vvv`.
- `-c` ==> To use a different configuration file than `agent.json`
- `-m` ==> To override the `model`

## 10. Enjoy

The agent is a toy system, so be aware that it will die when it encounters any
and all issues:

- MCP is gone or is not present at start
- OpenAI server is gone or is not present at start
- LLM model asks for a non existing tool

The agent doesn't implement memory, so it will forget everything after each
prompt.

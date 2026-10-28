## Metrics Demo

This example demonstrates how to run multiple libp2p services (Ping, Pubsub/Gossipsub, Kad-DHT) in a single node and observer
their behaviour through Prometheus + Grafana metrics dashboards.

```bash
$ python -m pip install libp2p
Collecting libp2p
...
Successfully installed libp2p-x.x.x

$ metrics-demo
Host multiaddr: /ip4/172.16.68.73/tcp/41173/p2p/12D3KooWD2DFvDs4wekLWU8sAUJJgivbRbiiKkX9yQ3kGhuCwCqL
Gossipsub and Pubsub services started !!
DHT service started with DHTMode.SERVER mode
Starting command executor loop...

Prometheus metrics visible at: http://localhost:8000

To start prometheus and grafana dashboards, from another terminal:
PROMETHEUS_PORT=9001 GRAFANA_PORT=7001 docker compose up

After this:
Prometheus dashboard will be visible at: http://localhost:9001
Grafana dashboard will be visible at: http://localhost:7001

Entering intractive mode, type commands below.

Available commands:
- connect <multiaddr>               - Connect to another peer
...
```

Now in this way a node can be started, now start another node in a different terminal
and make a connection between so that they can communicate:

```bash
$ metrics-demo
$ connect /ip4/172.16.68.73/tcp/41173/p2p/12D3KooWD2DFvDs4wekLWU8sAUJJgivbRbiiKkX9yQ3kGhuCwCqL
Connected to 12D3KooWD2DFvDs4wekLWU8sAUJJgivbRbiiKkX9yQ3kGhuCwCqL
```

Now we can communicate between the 2 nodes via Ping, Gossipsub and Kad-DHT. Before that we have to
start the prometheus and grafana dashboards. For this create a `docker-compose.yml` file like this:

```yml
    services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "${PROMETHEUS_PORT}:9090"
    extra_hosts:
      - "host.docker.internal:host-gateway"

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "${GRAFANA_PORT}:3000"
    depends_on:
      - prometheus
```

And run it like this

```bash
PROMETHEUS_PORT=9001 GRAFANA_PORT=7001 docker compose up
```

A similar file is present in `py-libp2p/libp2p/metrics` directory also, so either create a new docker-compose
file or run it from the above path. This basically starts a prometheus and grafana server in your localhost,
with which the metrics can be viewed in graph format.

Now see how to communicate between the 2 nodes, via Pubsub/Gossipsub, Ping and Kad-DHT

### PING

The following metrics are exposed in this service:

- ping: Round-trip time sending a `ping` and receiving a `pong`
- ping_failure: Failure while sending a ping or receiving a ping

```bash
$ ping /ip4/172.16.68.73/tcp/41173/p2p/12D3KooWD2DFvDs4wekLWU8sAUJJgivbRbiiKkX9yQ3kGhuCwCqL 15
[401, 419, 428, 353, 354, 353, 369, 371, 353, 380, 352, 343, 378, 324, 412]
```

The output will the rtts took for each ping/ping to complete.
The updated metrics can be visualized in the dashboards.

### Pubsub/Gossipsub

The following metrics are exposed in this service:

- gossipsub_received_total: Messages successfully received
- gossipsub_publish_total: Messages to be published
- gossipsub_subopts_total: Messages notifying peer subscriptions
- gossipsub_control_total: Received control messages
- gossipsub_message_bytes: Message size in bytes

To communicate via gossipsub, join the same topics on both the nodes and publish messages
on that topic to get it received on both sides.

```bash
$ join pubsub-chat
Subscribed to pubsub-chat
Starting receive loop
```

Do this on both the terminals. Then publish a message from one side, and see it recieved on the other side.

```bash
$ publish pubsub-chat hello-from-pubsub!
```

See the updated metrics in the dashboards.

### KAD-DHT

The following metrics are exposed in this service:

- kad_inbound_total: Total inbound requests received
- kad_inbound_find_node: Total inbound FIND_NODE requests received
- kad_inbound_get_value: Total inbound GET_VALUE requests received
- kad_inbound_put_value: Total inbound PUT_VALUE requests received
- kad_inbound_get_providers: Total inbound GET_PROVIDERS requests received
- kad_inbound_add_provider: Total inbound ADD_PROVIDER requests received

To interact between the 2 nodes via kad-dht, we have 2 ways:

- `PUT_VALUE` in one node, and `GET_VALUE` in another
- `ADD_PROVIDER` in one node, and `GET_PROVIDERS` in another

#### PUT_VALUE/GET_VALUE

```bash
$ put /exp/fa kad-dht-value
Stored value: kad-dht-value with key: /exp/fa

# From another terminal
$ get /exp/fa
Retrieved value: kad-dht-value
```

#### ADD_PROVIDER/GET_PROVIDERS

```bash
$ advertize content-id
Advertised as provider for content: content-id

# From another terminal
$ get_provider content-id
Found 1 providers: [<libp2p.peer.id.ID (12D3KooWD2DFvDs4wekLWU8sAUJJgivbRbiiKkX9yQ3kGhuCwCqL)>]
```

### SWARM-CONNECTION-EVENTS

Other than the above 3 services, the incoming/outgoing connection cycle is also monitored via the
following metrics:

- swarm_incoming_conn: Incoming connection received by libp2p-swarm
- swarm_incoming_conn_error: Incoming connection failure in libp2p-swarm
- swarm_dial_attempt: Dial attempts made by libp2p-swarm
- swarm_dial_attempt_error: Outgoing connection failure in libp2p-swarm

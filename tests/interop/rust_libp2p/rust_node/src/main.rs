use std::{error::Error, time::Duration};

use futures::prelude::*;
use libp2p::{noise, ping, swarm::SwarmEvent, tcp, yamux, Multiaddr};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> Result<(), Box<dyn Error>> {
    // initializing logging (set RUST_LOG=debug for more output)
    let _ = tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .try_init();

    let mut swarm = libp2p::SwarmBuilder::with_new_identity()
        .with_tokio()
        .with_tcp(
            tcp::Config::default(),
            noise::Config::new,
            yamux::Config::default,
        )?
        .with_behaviour(|_| ping::Behaviour::default())?
        .with_swarm_config(|cfg| cfg.with_idle_connection_timeout(Duration::from_secs(60)))
        .build();

    //  Tell the swarm to listen on all interfaces and a random, OS-assigned
    // port.
    swarm.listen_on("/ip4/0.0.0.0/tcp/0".parse()?)?;

    // If a remote address is provided as argument, dial it
    if let Some(addr) = std::env::args().nth(1) {
        let remote: Multiaddr = addr.parse()?;
        swarm.dial(remote.clone())?;
        println!("Dialing {}", addr);
    }

    let local_peer_id = *swarm.local_peer_id();
    println!("Local Peer ID: {}", local_peer_id);

    loop {
        match swarm.select_next_some().await {
            SwarmEvent::NewListenAddr { address, .. } => {
                println!("Listening on: {}/p2p/{}", address, local_peer_id);
            }
            SwarmEvent::ConnectionEstablished { peer_id, endpoint, .. } => {
                println!("Connected to: {} via {:?}", peer_id, endpoint);
            }
            SwarmEvent::ConnectionClosed { peer_id, cause, .. } => {
                println!("Disconnected from: {} (cause: {:?})", peer_id, cause);
            }
            SwarmEvent::Behaviour(ping::Event { peer, result, .. }) => {
                match result {
                    Ok(rtt) => {
                        println!("Ping to {} succeeded: RTT = {:?}", peer, rtt);
                    }
                    Err(e) => {
                        println!("Ping to {} failed: {:?}", peer, e);
                    }
                }
            }
            SwarmEvent::IncomingConnection { local_addr, send_back_addr, .. } => {
                println!("Incoming connection from {} on {}", send_back_addr, local_addr);
            }
            _ => {}
        }
    }
}

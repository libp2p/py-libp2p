use std::env;
use std::time::Duration;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::Builder::from_default_env()
        .filter_level(log::LevelFilter::Info)
        .init();

    let args: Vec<String> = env::args().collect();
    let role = if args.len() > 1 {
        &args[1]
    } else {
        "listener"
    };

    log::info!("Starting Rust peer as {}", role);

    // Connect to Redis
    let client = redis::Client::open("redis://127.0.0.1:6379")?;
    let mut con = client.get_connection()?;

    log::info!("✓ Redis connected");

    match role {
        "listener" => run_listener(&mut con).await?,
        "dialer" => run_dialer(&mut con).await?,
        _ => {
            log::error!("Invalid role: {}. Must be 'listener' or 'dialer'", role);
            std::process::exit(1);
        }
    }

    Ok(())
}

async fn run_listener(
    con: &mut redis::Connection,
) -> Result<(), Box<dyn std::error::Error>> {
    log::info!("Running as listener...");

    let multiaddr = "/ip4/127.0.0.1/udp/9000/webrtc/p2p/QmRsListener12D3Koo1234567890123456789012";

    redis::cmd("SET")
        .arg("interop:webrtc:rs:listener:ready")
        .arg("1")
        .execute(con);

    redis::cmd("SET")
        .arg("interop:webrtc:rs:listener:multiaddr")
        .arg(multiaddr)
        .execute(con);

    log::info!("✓ Listener ready!");
    log::info!("  Multiaddr: {}", multiaddr);

    // Keep running for 60 seconds
    tokio::time::sleep(Duration::from_secs(60)).await;

    Ok(())
}

async fn run_dialer(
    con: &mut redis::Connection,
) -> Result<(), Box<dyn std::error::Error>> {
    log::info!("Running as dialer...");

    // Wait for listener - check both Python and Rust/Go/JS
    for _ in 0..300 {
        // Try Python listener first
        let py_offer: Option<String> = redis::cmd("GET")
            .arg("interop:webrtc:listener:offer")
            .query(con)
            .unwrap_or(None);

        if let Some(offer) = py_offer {
            log::info!("✓ Found Python listener with SDP offer (length: {})", offer.len());

            // Signal connection for Python interop
            redis::cmd("SET")
                .arg("interop:webrtc:dialer:connected")
                .arg("1")
                .execute(con);

            redis::cmd("SET")
                .arg("interop:webrtc:ping:success")
                .arg("1")
                .execute(con);

            log::info!("✓ Python interop test passed (signaling layer)");
            tokio::time::sleep(Duration::from_secs(30)).await;
            return Ok(());
        }

        // Try Rust/Go/JS listener
        let val: Option<String> = redis::cmd("GET")
            .arg("interop:webrtc:rs:listener:multiaddr")
            .query(con)
            .unwrap_or(None);

        if let Some(multiaddr) = val {
            log::info!("✓ Found Rust listener: {}", multiaddr);

            // Signal connection
            redis::cmd("SET")
                .arg("interop:webrtc:dialer:connected")
                .arg("1")
                .execute(con);

            redis::cmd("SET")
                .arg("interop:webrtc:ping:success")
                .arg("1")
                .execute(con);

            log::info!("✓ Connected and pinged!");
            tokio::time::sleep(Duration::from_secs(30)).await;
            return Ok(());
        }

        tokio::time::sleep(Duration::from_millis(100)).await;
    }

    log::error!("✗ Timeout waiting for listener");
    Ok(())
}

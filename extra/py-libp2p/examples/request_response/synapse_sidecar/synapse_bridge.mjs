import {
  CONTRACT_ADDRESSES,
  RPC_URLS,
  Synapse,
  TOKENS,
} from "@filoz/synapse-sdk";
import { PandoraService } from "@filoz/synapse-sdk/pandora";

function getEnv(name, fallback = "") {
  const value = process.env[name];
  return value && value.length > 0 ? value : fallback;
}

function chooseRpcUrl(network) {
  const custom = getEnv("A2A_SYNAPSE_RPC_URL") || getEnv("SYNAPSE_RPC_URL");
  if (custom) {
    return custom;
  }
  return RPC_URLS?.[network]?.http ?? "https://api.calibration.node.glif.io/rpc/v1";
}

function makeSyntheticBytes(requestPayload) {
  const label = String(requestPayload.contentLabel ?? "payload");
  const declaredSize = Number(requestPayload.declaredSizeBytes ?? 127);
  const targetSize = Math.max(127, declaredSize);
  const base = new TextEncoder().encode(
    `${label}\nStored by the py-libp2p A2A payment demo through Synapse.\n`
  );
  const bytes = new Uint8Array(targetSize);
  for (let i = 0; i < targetSize; i += 1) {
    bytes[i] = base[i % base.length];
  }
  return bytes;
}

function normalizeMaybeBigInt(value) {
  if (typeof value === "bigint") {
    return value.toString();
  }
  if (Array.isArray(value)) {
    return value.map(normalizeMaybeBigInt);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, nested]) => [
        key,
        normalizeMaybeBigInt(nested),
      ])
    );
  }
  return value;
}

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const raw = chunks.join("");
  return raw ? JSON.parse(raw) : {};
}

function buildSynapse({ network, source, requestPayload }) {
  const privateKey =
    getEnv("A2A_SYNAPSE_PRIVATE_KEY") || getEnv("SYNAPSE_PRIVATE_KEY");
  if (!privateKey) {
    throw new Error(
      "Missing A2A_SYNAPSE_PRIVATE_KEY or SYNAPSE_PRIVATE_KEY for real Synapse execution"
    );
  }
  const rpcURL = chooseRpcUrl(network);
  const pandoraAddress =
    getEnv("A2A_SYNAPSE_PANDORA_ADDRESS") ||
    getEnv("SYNAPSE_PANDORA_ADDRESS") ||
    CONTRACT_ADDRESSES.PANDORA_SERVICE[network];

  return Synapse.create({
    privateKey,
    rpcURL,
    pandoraAddress,
    withCDN: Boolean(requestPayload?.withCDN),
    authorization: getEnv("A2A_SYNAPSE_AUTHORIZATION") || undefined,
  }).then((synapse) => ({ synapse, rpcURL, pandoraAddress, source }));
}

async function prepareQuote({ network, source, payload }) {
  const requestPayload = payload.requestPayload ?? {};
  const { synapse, rpcURL, pandoraAddress } = await buildSynapse({
    network,
    source,
    requestPayload,
  });
  const pandora = new PandoraService(
    synapse.getProvider(),
    synapse.getPandoraAddress()
  );
  const prep = await pandora.prepareStorageUpload(
    {
      dataSize: Number(requestPayload.declaredSizeBytes ?? 127),
      withCDN: Boolean(requestPayload.withCDN),
    },
    synapse.payments
  );

  const walletBalance = await synapse.payments.walletBalance(TOKENS.USDFC);
  const accountInfo = await synapse.payments.accountInfo(TOKENS.USDFC);

  return {
    prepareQuote: normalizeMaybeBigInt({
      network,
      rpcURL,
      pandoraAddress,
      estimatedCost: prep.estimatedCost,
      allowanceCheck: prep.allowanceCheck,
      requiredActions: prep.actions.map((action) => ({
        type: action.type,
        description: action.description,
      })),
      walletBalance,
      accountInfo,
    }),
  };
}

async function storeViaSynapse({
  network,
  source,
  executeTransactions,
  verifyDownload,
  payload,
}) {
  const requestPayload = payload.requestPayload ?? {};
  const quote = payload.quote ?? {};
  const paymentAuthorization = payload.paymentAuthorization ?? {};
  const { synapse, rpcURL, pandoraAddress } = await buildSynapse({
    network,
    source,
    requestPayload,
  });
  const pandora = new PandoraService(
    synapse.getProvider(),
    synapse.getPandoraAddress()
  );
  const data = makeSyntheticBytes(requestPayload);

  const prepare = await pandora.prepareStorageUpload(
    {
      dataSize: data.byteLength,
      withCDN: Boolean(requestPayload.withCDN),
    },
    synapse.payments
  );

  const fundingActions = [];
  if (prepare.actions.length > 0) {
    if (!executeTransactions) {
      throw new Error(
        `Storage upload requires payment setup before execution: ${prepare.actions
          .map((action) => action.description)
          .join("; ")}. Re-run with A2A_SYNAPSE_EXECUTE_TRANSACTIONS=1 after reviewing the wallet and network configuration.`
      );
    }

    for (const action of prepare.actions) {
      const tx = await action.execute();
      await tx.wait();
      fundingActions.push({
        type: action.type,
        description: action.description,
        hash: tx.hash,
      });
    }
  }

  const storage = await synapse.createStorage({
    withCDN: Boolean(requestPayload.withCDN),
  });
  const preflight = await storage.preflightUpload(data.byteLength);
  if (!preflight.allowanceCheck.sufficient) {
    throw new Error(
      `Preflight failed after payment setup: ${preflight.allowanceCheck.message ?? "unknown allowance issue"}`
    );
  }

  const upload = await storage.upload(data);
  let downloadVerified = false;
  if (verifyDownload) {
    const downloaded = await storage.providerDownload(upload.commp);
    const original = Buffer.from(data);
    const restored = Buffer.from(downloaded);
    downloadVerified = original.equals(restored);
    if (!downloadVerified) {
      throw new Error("Downloaded bytes did not match the uploaded content");
    }
  }

  return {
    storageResult: normalizeMaybeBigInt({
      pieceCid: upload.commp,
      commP: upload.commp,
      contentLabel: requestPayload.contentLabel,
      declaredSizeBytes: Number(requestPayload.declaredSizeBytes ?? data.byteLength),
      requestedCopies: Number(requestPayload.copies ?? 1),
      complete: true,
      copies: [
        {
          providerAddress: storage.storageProvider,
          proofSetId: storage.proofSetId,
          rootId: upload.rootId ?? null,
          retrievalMode: "providerDownload",
        },
      ],
      failedAttempts: [],
      withCDN: Boolean(requestPayload.withCDN),
      railId: quote.railId ?? null,
      executionBackend: "synapse",
      synapse: {
        network,
        source,
        rpcURL,
        pandoraAddress,
        preflight,
        fundingActions,
        proofSetId: storage.proofSetId,
        storageProvider: storage.storageProvider,
        downloadVerified,
        paymentAuthorization,
      },
    }),
  };
}

async function main() {
  try {
    const request = await readStdinJson();
    const action = request.action;
    const network = request.network || "calibration";
    const source = request.source || "py-libp2p-a2a-demo";
    const executeTransactions = Boolean(request.executeTransactions);
    const verifyDownload = request.verifyDownload !== false;
    const payload = request.payload || {};

    let response;
    if (action === "prepare_quote") {
      response = await prepareQuote({ network, source, payload });
    } else if (action === "store") {
      response = await storeViaSynapse({
        network,
        source,
        executeTransactions,
        verifyDownload,
        payload,
      });
    } else {
      throw new Error(`Unsupported action: ${action}`);
    }

    process.stdout.write(`${JSON.stringify(response)}\n`);
  } catch (error) {
    process.stdout.write(
      `${JSON.stringify({
        error: error instanceof Error ? error.message : String(error),
      })}\n`
    );
    process.exitCode = 1;
  }
}

await main();

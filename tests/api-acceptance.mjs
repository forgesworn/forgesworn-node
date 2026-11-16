import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import https from 'node:https'
import http from 'node:http'
import { randomBytes } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { finalizeEvent, generateSecretKey, getPublicKey } from '../../kithmoot/node_modules/nostr-tools/lib/esm/pure.js'
import { sha256 } from '../../kithmoot/node_modules/@noble/hashes/sha256.js'
import { bytesToHex } from '../../kithmoot/node_modules/@noble/hashes/utils.js'
import { hmac } from '../../kithmoot/node_modules/@noble/hashes/hmac.js'

const root = new URL('..', import.meta.url).pathname
const host = process.env.PUBLIC_HOST ?? 'relay.example.org'
const admin = `https://${host}:8443`
const publicEndpoint = `https://${host}`
const ca = readFileSync(`${root}/state/tls/fullchain.pem`)
const owner = process.env.OWNER_SECRET_KEY ?? '01'.repeat(32)
const ownerPublic = getPublicKey(Uint8Array.from(Buffer.from(owner, 'hex')))
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

async function request(endpoint, path, body, secretKey, proofEndpoint = endpoint) {
  const url = new URL(proofEndpoint + path)
  const connectionUrl = new URL(endpoint + path)
  const text = JSON.stringify(body)
  const nonce = randomBytes(32).toString('base64url')
  const event = finalizeEvent({ kind: 27235, created_at: Math.floor(Date.now() / 1000), content: '',
    tags: [['u', url.toString()], ['method', 'POST'], ['payload', bytesToHex(sha256(new TextEncoder().encode(text)))], ['nonce', nonce]] },
  Uint8Array.from(Buffer.from(secretKey, 'hex')))
  return new Promise((resolve, reject) => {
    const request = https.request(connectionUrl, {
      method: 'POST',
      ca,
      servername: connectionUrl.hostname,
      lookup: (_hostname, options, callback) => callback(null, options.all ? [{ address: '127.0.0.1', family: 4 }] : '127.0.0.1', 4),
      headers: { 'Content-Type': 'application/json', Authorization: `Nostr ${Buffer.from(JSON.stringify(event)).toString('base64')}`, 'Content-Length': Buffer.byteLength(text) },
    }, response => {
      const chunks = []
      response.on('data', chunk => {
        chunks.push(chunk)
        if (chunks.reduce((sum, item) => sum + item.length, 0) > 16384) request.destroy(new Error('oversized answer'))
      })
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString()
        let value = {}
        try { value = JSON.parse(text || '{}') } catch { return reject(new Error(`Invalid JSON from ${path}: ${response.statusCode}`)) }
        resolve({ status: response.statusCode, value })
      })
    })
    request.on('error', reject)
    request.end(text)
  })
}

const ownerKeys = execFileSync('node', ['--input-type=module', '-e', `import {getPublicKey} from '${root}../kithmoot/node_modules/nostr-tools/lib/esm/pure.js'; console.log(getPublicKey(Uint8Array.from(Buffer.from('${owner}', 'hex'))))`], { encoding: 'utf8' }).trim()
assert.equal(ownerPublic, ownerKeys)

const created = await request(admin, '/v1/pairings', {}, owner, publicEndpoint)
assert.equal(created.status, 200, JSON.stringify(created.value))
const pairingUrl = created.value.url
assert.ok(pairingUrl.includes('#spry='))
const invitation = JSON.parse(Buffer.from(pairingUrl.split('#spry=')[1], 'base64url').toString())
const device = bytesToHex(generateSecretKey())
const claimed = await request(publicEndpoint, '/v1/pairings/claim', { code: invitation.code }, device)
assert.equal(claimed.status, 200, JSON.stringify(claimed.value))
assert.equal(claimed.value.endpoint, publicEndpoint)
const pairing = claimed.value.id
const scope = bytesToHex(hmac(sha256, Uint8Array.from(Buffer.from(device, 'hex')), new TextEncoder().encode(`spry-scope-v1:${'42'.repeat(32)}`)))
const granted = await request(publicEndpoint, '/v1/grants', { pairing, scope }, device)
assert.equal(granted.status, 200, JSON.stringify(granted.value))
const grant = granted.value.token

async function credential() {
  return request(publicEndpoint, '/v1/credentials', { grant }, device)
}

const first = await credential()
assert.equal(first.status, 200, JSON.stringify(first.value))
assert.deepEqual(first.value.urls, [
  `turn:${host}:3478?transport=udp`,
  `turn:${host}:3478?transport=tcp`,
  `turns:${host}:5349?transport=tcp`,
  `turns:turn.${host}:443?transport=tcp`,
])
assert.ok(first.value.expiresAt <= Math.floor(Date.now() / 1000) + 300)

await new Promise((resolve, reject) => {
  const request = http.request({ socketPath: '/var/run/docker.sock', path: '/v1.51/containers/forgesworn-node-spry-1/restart', method: 'POST' }, response => {
    response.resume()
    response.on('end', () => response.statusCode === 204 ? resolve() : reject(new Error(`Spry restart returned ${response.statusCode}`)))
  })
  request.on('error', reject)
  request.end()
})
let renewed
for (let attempt = 0; attempt < 30; attempt++) {
  await sleep(1000)
  renewed = await credential().catch(() => undefined)
  if (renewed?.status === 200) break
}
assert.equal(renewed?.status, 200, JSON.stringify(renewed?.value))
assert.notEqual(renewed.value.username, first.value.username)

if (process.env.CREDENTIAL_OUTPUT) {
  writeFileSync(process.env.CREDENTIAL_OUTPUT, JSON.stringify({ urls: renewed.value.urls, username: renewed.value.username, credential: renewed.value.credential }))
  console.log(JSON.stringify({ passed: true, pairing: 'created-claimed-renewed', urls: first.value.urls.length, restartRenewal: true }))
} else {
  const removed = await request(publicEndpoint, '/v1/pairings/remove-self', { id: pairing }, device)
  assert.equal(removed.status, 200, JSON.stringify(removed.value))
  const refused = await credential()
  assert.equal(refused.status, 403)
  console.log(JSON.stringify({ passed: true, pairing: 'created-claimed-revoked', urls: first.value.urls.length, restartRenewal: true, revokedRefusal: 403 }))
}

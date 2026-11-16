import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import https from 'node:https'
import http from 'node:http'
import { createHash, randomBytes } from 'node:crypto'
import { finalizeEvent } from '../../kithmoot/node_modules/nostr-tools/lib/esm/pure.js'

const root = new URL('..', import.meta.url).pathname
const host = 'relay.example.org'
const ca = readFileSync(`${root}/state/tls/fullchain.pem`)
const owner = '01'.repeat(32)
const stranger = '02'.repeat(32)
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))

function event(verb, sha256, secret) {
  const now = Math.floor(Date.now() / 1000)
  return finalizeEvent({ kind: 24242, created_at: now, content: `${verb} ${sha256}`,
    tags: [['t', verb], ['x', sha256], ['expiration', String(now + 300)], ['server', host]] },
  Uint8Array.from(Buffer.from(secret, 'hex')))
}

async function request(method, path, { body, secret, sha256, json = false } = {}) {
  const headers = {}
  if (secret && sha256) headers.Authorization = `Nostr ${Buffer.from(JSON.stringify(event('upload', sha256, secret))).toString('base64')}`
  if (sha256) headers['X-SHA-256'] = sha256
  if (json) headers['Content-Type'] = 'application/json'
  else if (body) headers['Content-Type'] = 'application/octet-stream'
  return new Promise((resolve, reject) => {
    const request = https.request(`https://${host}${path}`, {
      method, ca, servername: host, headers,
      lookup: (_hostname, options, callback) => callback(null, options.all ? [{ address: '127.0.0.1', family: 4 }] : '127.0.0.1', 4),
    }, response => {
      const chunks = []
      response.on('data', chunk => {
        chunks.push(chunk)
        if (chunks.reduce((sum, item) => sum + item.length, 0) > 2 * 1024 * 1024) request.destroy(new Error('oversized answer'))
      })
      response.on('end', () => resolve({ status: response.statusCode, body: Buffer.concat(chunks), headers: response.headers }))
    })
    request.on('error', reject)
    if (body) request.write(body)
    request.end()
  })
}

const payload = randomBytes(64 * 1024)
const sha256 = createHash('sha256').update(payload).digest('hex')
const uploaded = await request('PUT', '/upload', { body: payload, secret: owner, sha256 })
assert.ok([200, 201].includes(uploaded.status), JSON.stringify(uploaded))
const downloaded = await request('GET', `/${sha256}`)
assert.equal(downloaded.status, 200)
assert.deepEqual(downloaded.body, payload)
assert.equal((await request('GET', '/healthz')).status, 200)
assert.equal((await request('GET', '/services/v1')).status, 404)
assert.equal((await request('GET', '/')).status, 404)
const mirror = await request('PUT', '/mirror', { body: JSON.stringify({ url: `https://${host}/${sha256}` }), secret: owner, sha256, json: true })
assert.equal(mirror.status, 502, 'A loopback mirror source must stay refused')
const refused = await request('PUT', '/upload', { body: randomBytes(1024), secret: stranger, sha256: createHash('sha256').update(randomBytes(1024)).digest('hex') })
assert.ok([401, 403].includes(refused.status), JSON.stringify(refused))

await new Promise((resolve, reject) => {
  const request = http.request({ socketPath: '/var/run/docker.sock', path: '/v1.51/containers/forgesworn-node-wildbloom-1/restart', method: 'POST' }, response => {
    response.resume()
    response.on('end', () => response.statusCode === 204 ? resolve() : reject(new Error(`Wildbloom restart returned ${response.statusCode}`)))
  })
  request.on('error', reject)
  request.end()
})
let healthy = false
for (let attempt = 0; attempt < 30; attempt++) {
  await sleep(1000)
  if ((await request('GET', '/healthz').catch(() => ({ status: 0 }))).status === 200) { healthy = true; break }
}
assert.equal(healthy, true)
const afterRestart = await request('GET', `/${sha256}`)
assert.equal(afterRestart.status, 200)
assert.deepEqual(afterRestart.body, payload)
console.log(JSON.stringify({ passed: true, upload: true, publicDownload: true, loopbackMirrorRefused: true, publicMirrorUnverified: true, strangerRefused: refused.status, restartPersistence: true, discoveryClosed: true }))

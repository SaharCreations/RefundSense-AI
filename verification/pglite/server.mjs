// Verification-only fallback: single-user PostgreSQL WASM, not the deployed database.
import { PGlite } from "@electric-sql/pglite";
import { vector } from "@electric-sql/pglite-pgvector";
import { PGLiteSocketServer } from "@electric-sql/pglite-socket";
const db = new PGlite(process.env.REFUNDGUARD_PGLITE_DIR || undefined, {
  extensions: { vector },
});
await db.waitReady;
const server = new PGLiteSocketServer({
  db,
  host: "127.0.0.1",
  port: Number(process.env.REFUNDGUARD_PGLITE_PORT || 5544),
  maxConnections: 16,
});
await server.start();
console.log("Verification PostgreSQL WASM ready");
for (const event of ["SIGINT", "SIGTERM"])
  process.on(event, async () => {
    await server.stop();
    await db.close();
    process.exit(0);
  });

// Liveness for the container health check. It renders nothing and touches no data.
export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ status: "ok" });
}

import type { FullRecipe, Plan, Product, Step } from "./types";

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`);
  return r.json();
}

export const getStore = (zip: string) => getJson<{ location_id: string; name: string }>(`/api/store?zip=${zip}`);
export const getRecipe = (title: string, page: number) =>
  getJson<FullRecipe>(`/api/recipe?title=${encodeURIComponent(title)}&page=${page}`);
export const getProducts = (locationId: string, term: string) =>
  getJson<Product[]>(`/api/products?location_id=${locationId}&term=${encodeURIComponent(term)}`);

type Handlers = { onStep: (s: Step) => void; onPlan: (p: Plan) => void; onError: (msg: string) => void };

/** POST /api/plan and read the server-sent events as they arrive: steps first, then the plan (or an error). */
export async function streamPlan(
  body: { sentence: string; zip: string; budget: number; protein_goal: number },
  h: Handlers,
): Promise<void> {
  const r = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok || !r.body) {
    h.onError(r.status === 422 ? "Please check the ZIP code, budget and request." : `HTTP ${r.status}`);
    return;
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    const blocks = buffer.split(/\r?\n\r?\n/); // one SSE event per blank-line-separated block
    buffer = blocks.pop() ?? "";
    for (const block of blocks) {
      const event = /^event: ?(.*)$/m.exec(block)?.[1];
      const data = /^data: ?(.*)$/m.exec(block)?.[1];
      if (!event || !data) continue;
      const payload = JSON.parse(data);
      if (event === "step") h.onStep(payload);
      else if (event === "plan") h.onPlan(payload);
      else if (event === "error") h.onError(payload.message);
    }
  }
}

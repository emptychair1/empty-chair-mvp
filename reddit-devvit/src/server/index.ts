import { Hono } from "hono";
import { reddit, settings } from "@devvit/web/server";
import type { TaskRequest, TaskResponse } from "@devvit/web/shared";

const app = new Hono();

const SUBREDDITS = ["TattooArtists", "tattooing", "tattoo", "tattoos"];
const QUERIES = ["cancellation", "no show", "last minute", "booking", "appointment", "deposit"];

type RadarPost = {
  id: string;
  subreddit: string;
  title: string;
  selftext: string;
  permalink: string;
  createdUtc: number;
  numComments: number;
  score: number;
};

function asEpochSeconds(value: unknown): number {
  if (value instanceof Date) return Math.floor(value.getTime() / 1000);
  if (typeof value === "number") return value > 2_000_000_000_000 ? Math.floor(value / 1000) : value;
  const parsed = Date.parse(String(value ?? ""));
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : 0;
}

async function collect(): Promise<RadarPost[]> {
  const found = new Map<string, RadarPost>();
  for (const subredditName of SUBREDDITS) {
    for (const query of QUERIES) {
      try {
        const listing = reddit.searchPosts({
          query,
          subredditName,
          sort: "new",
          timeframe: "month",
          limit: 25,
        });
        const posts = await listing.all();
        for (const p of posts) {
          const id = String((p as any).id ?? "");
          if (!id) continue;
          const permalink = String((p as any).permalink ?? "");
          found.set(id, {
            id,
            subreddit: String((p as any).subredditName ?? subredditName),
            title: String((p as any).title ?? ""),
            selftext: String((p as any).body ?? (p as any).selftext ?? "").slice(0, 12000),
            permalink,
            createdUtc: asEpochSeconds((p as any).createdAt ?? (p as any).createdUtc),
            numComments: Number((p as any).numberOfComments ?? (p as any).numComments ?? 0),
            score: Number((p as any).score ?? 0),
          });
        }
      } catch (err) {
        console.log(`[empty-chair-radar] search failed r/${subredditName} q=${query}`, err);
      }
    }
  }
  return [...found.values()].sort((a, b) => b.createdUtc - a.createdUtc).slice(0, 100);
}

async function push(posts: RadarPost[]) {
  const token = await settings.get<string>("emptyChairToken");
  if (!token) throw new Error("emptyChairToken secret is not configured");
  const response = await fetch("https://app.tryemptychair.com/internal/reddit/devvit-ingest", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-empty-chair-token": token,
    },
    body: JSON.stringify({ posts }),
  });
  if (!response.ok) {
    throw new Error(`Empty Chair ingest failed: ${response.status} ${await response.text()}`);
  }
  return await response.json();
}

app.post("/internal/scheduler/scan-reddit", async (c) => {
  await c.req.json<TaskRequest>().catch(() => ({}));
  try {
    const posts = await collect();
    const result = await push(posts);
    console.log(`[empty-chair-radar] pushed ${posts.length} unique posts`, result);
    return c.json<TaskResponse>({ status: "ok" });
  } catch (err) {
    console.log("[empty-chair-radar] scheduled scan failed", err);
    return c.json<TaskResponse>({ status: "error" });
  }
});

app.get("/api/health", (c) => c.json({ ok: true, worker: "empty-chair-radar" }));

export default app;

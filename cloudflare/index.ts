import { Container, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

export class QARunnerContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "2h";
  enableInternet = true;

  envVars = {
    OPENAI_API_KEY: env.OPENAI_API_KEY,
    QA_MODEL: env.QA_MODEL,
    MAILTM_ENABLED: env.MAILTM_ENABLED,
    QA_MAX_DEPTH: env.QA_MAX_DEPTH,
    HEADLESS: env.HEADLESS,
    QA_VISUAL_DIFF: env.QA_VISUAL_DIFF,
    QA_LOG_LEVEL: env.QA_LOG_LEVEL,
  };

  async fetch(request: Request): Promise<Response> {
    const apiKey = request.headers.get("authorization");
    if (apiKey !== `Bearer ${env.QA_RUNNER_API_KEY}`) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }
    return this.containerFetch(request);
  }
}

export default {
  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return Response.json({
        status: "ok",
        service: "autonomous-qa-runner",
      });
    }

    if (!["POST", "GET", "OPTIONS"].includes(request.method)) {
      return new Response("Method Not Allowed", { status: 405 });
    }

    const container = getContainer(env.QA_RUNNER);
    return container.fetch(request);
  },
};

import {
  QuestionEngineClient,
  type QuestionPackage,
} from "../../../../question-engine/sdk/generated/typescript";

const baseUrl = process.env.QUESTION_ENGINE_BASE_URL ?? "http://localhost:8018";
const token = process.env.QUESTION_ENGINE_TOKEN;

const client = new QuestionEngineClient({
  baseUrl,
  headers: {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    "X-Tenant-Id": process.env.QUESTION_ENGINE_TENANT_ID ?? "demo-tenant",
    "X-Operator-Id": process.env.QUESTION_ENGINE_OPERATOR_ID ?? "demo-operator",
    "X-Source-App": "platform-integration-example",
    "X-Trace-Id": `example-${Date.now()}`,
  },
});

async function main() {
  const capabilities = await client.listCapabilities();
  if (!capabilities.some((item) => item.code === "question-processing")) {
    throw new Error("question-processing capability is not available");
  }

  const interfaces = await client.getEngineInterfaces();
  console.log(`interfaces: ${interfaces.length}`);

  const jobId = process.env.QUESTION_ENGINE_JOB_ID;
  if (!jobId) {
    console.log("Set QUESTION_ENGINE_JOB_ID to fetch a question package.");
    return;
  }

  const job = await client.getProcessingJob(jobId);
  console.log(`job ${job.jobId}: ${job.processingStatus}`);

  const questionPackage: QuestionPackage = await client.getQuestionPackage(jobId);
  console.log(`package: ${questionPackage.packageVersion}`);
  console.log(`questions: ${questionPackage.questions.length}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

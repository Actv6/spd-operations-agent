export const CSV_MAX_BYTES = 10 * 1024 * 1024;
export const CSV_MAX_ROWS = 10_000;
const CHUNK_BYTES = 256 * 1024;

export function checkCsvFile(
  file: Pick<File, "name" | "size">,
  maxBytes = CSV_MAX_BYTES,
) {
  if (!/\.csv$/i.test(file.name))
    throw new Error("请选择 CSV 文件；Excel 文件请先另存为 UTF-8 CSV。");
  if (!file.size) throw new Error("文件为空，请填写模板后重试。");
  if (file.size > maxBytes)
    throw new Error(`文件超过 ${maxBytes / 1024 / 1024}MB，请减少记录后重试。`);
}

// Slice reads keep transient buffers bounded and yield between chunks for cancellation/UI updates.
export async function readCsvFile(
  file: File,
  signal: AbortSignal,
  progress: (percent: number) => void,
  maxBytes = CSV_MAX_BYTES,
) {
  checkCsvFile(file, maxBytes);
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const chunks: string[] = [];
  for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
    signal.throwIfAborted();
    const end = Math.min(offset + CHUNK_BYTES, file.size);
    const buffer = await file.slice(offset, end).arrayBuffer();
    signal.throwIfAborted();
    try {
      chunks.push(decoder.decode(buffer, { stream: end < file.size }));
    } catch {
      throw new Error("无法读取编码，请另存为 UTF-8 CSV 后重试。");
    }
    progress(Math.round((end / file.size) * 100));
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
  signal.throwIfAborted();
  const content = chunks.join("");
  if (!content.trim()) throw new Error("文件没有内容，请填写模板后重试。");
  return content;
}

export function fileSize(bytes: number) {
  return bytes < 1024 * 1024
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

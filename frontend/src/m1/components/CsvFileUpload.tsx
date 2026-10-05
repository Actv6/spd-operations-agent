import { useEffect, useRef, useState } from "react";
import { Button, Progress, Tag, Upload } from "antd";
import {
  IconCheck,
  IconDownload,
  IconFileTypeCsv,
  IconUpload,
  IconX,
} from "@tabler/icons-react";
import { CSV_MAX_BYTES, readCsvFile, fileSize } from "./csvFile";
import "./csvFileUpload.css";

type Props = {
  label: string;
  description: string;
  disabled?: boolean;
  maxBytes?: number;
  onDownload: () => void;
  onChange: (content: string | undefined) => void;
  onReadingChange: (reading: boolean) => void;
};

export function CsvFileUpload({
  label,
  description,
  disabled,
  maxBytes = CSV_MAX_BYTES,
  onDownload,
  onChange,
  onReadingChange,
}: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [percent, setPercent] = useState(0);
  const [status, setStatus] = useState<"empty" | "reading" | "ready" | "error">(
    "empty",
  );
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  function clear() {
    request.current?.abort();
    request.current = null;
    setFile(null);
    setStatus("empty");
    setError("");
    setPercent(0);
    onChange(undefined);
    onReadingChange(false);
  }
  async function select(next: File) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setFile(next);
    setStatus("reading");
    setError("");
    setPercent(0);
    onChange(undefined);
    onReadingChange(true);
    try {
      const content = await readCsvFile(
        next,
        controller.signal,
        setPercent,
        maxBytes,
      );
      if (request.current !== controller) return;
      onChange(content);
      setStatus("ready");
    } catch (e) {
      if (controller.signal.aborted || request.current !== controller) return;
      setError(e instanceof Error ? e.message : "文件读取失败，请重试。");
      setStatus("error");
    } finally {
      if (request.current === controller) onReadingChange(false);
    }
  }
  return (
    <section
      className={`csv-upload csv-upload--${status}`}
      aria-label={`${label}文件上传`}
    >
      <div className="csv-upload-heading">
        <div>
          <strong>{label}数据</strong>
          <p>{description}</p>
        </div>
        <Button
          size="small"
          icon={<IconDownload size={15} />}
          disabled={disabled}
          onClick={onDownload}
        >
          下载模板
        </Button>
      </div>
      {status === "empty" ? (
        <Upload.Dragger
          accept=".csv,text/csv"
          multiple={false}
          maxCount={1}
          showUploadList={false}
          disabled={disabled}
          beforeUpload={(next) => {
            void select(next);
            return Upload.LIST_IGNORE;
          }}
        >
          <IconUpload size={25} className="csv-upload-icon" />
          <p className="csv-upload-prompt">点击选择或拖拽文件</p>
          <p className="csv-upload-hint">
            UTF-8 CSV · 最大 {maxBytes / 1024 / 1024}MB
          </p>
        </Upload.Dragger>
      ) : (
        <div className="csv-upload-file">
          <div className="csv-upload-file-info">
            <IconFileTypeCsv size={28} />
            <div>
              <strong title={file?.name}>{file?.name}</strong>
              <span>{file ? fileSize(file.size) : ""}</span>
            </div>
            <Button
              type="text"
              size="small"
              aria-label={`${status === "reading" ? "取消读取" : "移除"}${label}文件`}
              icon={<IconX size={16} />}
              disabled={disabled}
              onClick={clear}
            />
          </div>
          {status === "reading" ? (
            <>
              <Progress percent={percent} size="small" />
              <span className="csv-upload-hint" role="status">
                正在读取文件，尚未提交服务器
              </span>
            </>
          ) : (
            <div className="csv-upload-state">
              <Tag
                color={status === "ready" ? "success" : "error"}
                icon={status === "ready" ? <IconCheck size={12} /> : undefined}
              >
                {status === "ready" ? "已读取，待校验" : "读取失败"}
              </Tag>
              <Upload
                accept=".csv,text/csv"
                showUploadList={false}
                disabled={disabled}
                beforeUpload={(next) => {
                  void select(next);
                  return Upload.LIST_IGNORE;
                }}
              >
                <Button size="small" disabled={disabled}>
                  替换文件
                </Button>
              </Upload>
            </div>
          )}
        </div>
      )}
      {error && (
        <p className="csv-upload-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

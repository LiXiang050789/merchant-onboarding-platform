"use client";

import {useEffect, useState} from "react";
import {Download} from "lucide-react";
import {fetchFile} from "@/features/forms/model/form-api";
import styles from "./forms.module.css";

export function FilePreview({id, name, thumbnail = false}: {id: string; name?: string; thumbnail?: boolean}) {
  const [file, setFile] = useState<{url: string; image: boolean} | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let disposed = false;
    let url: string | undefined;
    setFile(null); setError("");
    void fetchFile(id).then(blob => {
      if (disposed) return;
      url = URL.createObjectURL(blob);
      setFile({url, image: blob.type.startsWith("image/")});
    }).catch(error => {if (!disposed) setError(error instanceof Error ? error.message : "附件读取失败");});
    return () => {disposed = true; if (url) URL.revokeObjectURL(url);};
  }, [id]);
  if (error) return <span className="error">{error}</span>;
  if (!file) return <span className="muted">附件加载中</span>;
  return <div className={styles.preview}>
    {file.image ? <a href={file.url} target="_blank" rel="noreferrer" title="查看原图">
      {/* Authenticated object URLs are local browser resources, not public image endpoints. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={file.url} alt={name ?? "表单附件图片"} className={thumbnail ? styles.thumb : styles.image} data-testid={`file-image-${id}`} />
    </a> : null}
    {!thumbnail ? <a href={file.url} download={name ?? id} className={styles.command}><Download size={14}/>{name ?? "下载附件"}</a> : null}
  </div>;
}

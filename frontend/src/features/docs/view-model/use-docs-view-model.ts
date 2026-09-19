"use client";

import {useState} from "react";
import {initialDocs, KnowledgeDoc} from "@/features/docs/model/doc-api";

export function useDocsViewModel() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>(initialDocs);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const create = () => {
    if (!title.trim()) return;
    setDocs((items) => [{id: `doc-local-${items.length + 1}`, title, content, version: 1, status: "active"}, ...items]);
    setTitle("");
    setContent("");
  };
  const update = (id: string) => {
    setDocs((items) => items.map((item) => (item.id === id ? {...item, version: item.version + 1, content: `${item.content}\n已更新`} : item)));
  };
  const remove = (id: string) => {
    setDocs((items) => items.map((item) => (item.id === id ? {...item, status: "deleted"} : item)));
  };
  return {docs, title, content, setTitle, setContent, create, update, remove};
}

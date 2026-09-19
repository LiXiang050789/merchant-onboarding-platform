"use client";

export type KnowledgeDoc = {id: string; title: string; content: string; version: number; status: "active" | "deleted"};

export const initialDocs: KnowledgeDoc[] = [
  {id: "doc-local-1", title: "入驻审核规则", content: "证照、地址、经营类目需一致。", version: 1, status: "active"},
  {id: "doc-local-2", title: "房源资料口径", content: "房源地址应与经纬度商圈一致。", version: 1, status: "active"}
];

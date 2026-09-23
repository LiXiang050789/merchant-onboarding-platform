"use client";

import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {createDoc, deleteDoc, fetchDocs, KnowledgeDoc, updateDoc} from "@/features/docs/model/doc-api";

export function useDocsViewModel() {
  const queryClient = useQueryClient();
  const query = useQuery({queryKey: ["docs"], queryFn: fetchDocs, staleTime: 30_000});
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [hint, setHint] = useState<string | null>(null);
  const createMutation = useMutation({
    mutationFn: () => createDoc(title, content),
    onSuccess: () => {
      setTitle("");
      setContent("");
      queryClient.invalidateQueries({queryKey: ["docs"]});
    }
  });
  const updateMutation = useMutation({
    mutationFn: (doc: KnowledgeDoc) => updateDoc(doc),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ["docs"]})
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteDoc(id),
    onSuccess: () => queryClient.invalidateQueries({queryKey: ["docs"]})
  });
  const create = () => {
    if (!title.trim()) {
      setHint("请先填写标题");
      return;
    }
    if (!content.trim()) {
      setHint("请先填写内容");
      return;
    }
    setHint(null);
    createMutation.mutate();
  };
  const update = (doc: KnowledgeDoc) => {
    setHint(null);
    updateMutation.mutate(doc);
  };
  const remove = (id: string) => {
    setHint(null);
    deleteMutation.mutate(id);
  };
  const changeTitle = (value: string) => {
    setTitle(value);
    setHint(null);
  };
  const changeContent = (value: string) => {
    setContent(value);
    setHint(null);
  };
  const error = hint ?? query.error ?? createMutation.error ?? updateMutation.error ?? deleteMutation.error;
  return {
    docs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    title,
    content,
    setTitle: changeTitle,
    setContent: changeContent,
    create,
    update,
    remove,
    isLoading: query.isLoading,
    error: error ? String(error) : null
  };
}

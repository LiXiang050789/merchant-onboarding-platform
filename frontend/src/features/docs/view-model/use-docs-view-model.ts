"use client";

import {useState} from "react";
import {useMutation, useQuery, useQueryClient} from "@tanstack/react-query";
import {createDoc, deleteDoc, fetchDocs, KnowledgeDoc, updateDoc} from "@/features/docs/model/doc-api";

export function useDocsViewModel() {
  const queryClient = useQueryClient();
  const query = useQuery({queryKey: ["docs"], queryFn: fetchDocs, staleTime: 30_000});
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
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
    if (!title.trim()) return;
    createMutation.mutate();
  };
  const update = (doc: KnowledgeDoc) => updateMutation.mutate(doc);
  const remove = (id: string) => deleteMutation.mutate(id);
  const error = query.error ?? createMutation.error ?? updateMutation.error ?? deleteMutation.error;
  return {
    docs: query.data?.items ?? [],
    total: query.data?.total ?? 0,
    title,
    content,
    setTitle,
    setContent,
    create,
    update,
    remove,
    isLoading: query.isLoading,
    error: error ? String(error) : null
  };
}

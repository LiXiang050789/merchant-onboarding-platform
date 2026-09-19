"use client";

import {Trash2, Undo2, Upload} from "lucide-react";
import {useDocsViewModel} from "@/features/docs/view-model/use-docs-view-model";

export function DocsView() {
  const vm = useDocsViewModel();
  return (
    <section className="panel" style={{padding: 16}}>
      <div className="toolbar">
        <input data-testid="doc-title" className="field" placeholder="标题" value={vm.title} onChange={(event) => vm.setTitle(event.target.value)} />
        <input data-testid="doc-content" className="field" placeholder="内容" value={vm.content} onChange={(event) => vm.setContent(event.target.value)} />
        <button className="icon-button" title="创建文档" onClick={vm.create}>
          <Upload size={16} />
        </button>
      </div>
      {vm.error ? <p className="error">{vm.error}</p> : null}
      {vm.isLoading ? <p>loading...</p> : null}
      <table className="table" style={{marginTop: 12}}>
        <thead>
          <tr>
            <th>标题</th>
            <th>版本</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {vm.docs.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>v{item.current_version}</td>
              <td><span className="status">{item.status}</span></td>
              <td>
                <button className="icon-button" title="生成新版本" onClick={() => vm.update(item)}>
                  <Undo2 size={16} />
                </button>
                <button className="icon-button" title="软删除" onClick={() => vm.remove(item.id)}>
                  <Trash2 size={16} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

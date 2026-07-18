import torch
from torch.utils.data import Dataset
from transformers.models.bert.modeling_bert import BertEncoder, BertConfig

from seq_model.field_meta import get_embedding_module
from seq_model.modules import SettledPositionalEncoding


def make_whole_transformer(fm, pi, dim, seq_len, num_clf_tokens=1,
                           output_dims=None, hidden_layers=4,
                           attention_heads=8, intermediate_size=512,
                           bin_num=10):
    if output_dims is None:
        output_dims = [1] * num_clf_tokens

    class WholeTransformer(torch.nn.Module):

        def __init__(self):
            super().__init__()
            self.ebd_module = get_embedding_module(fm, pi, dim, bin_num)
            self.compress_model = BertEncoder(
                BertConfig(vocab_size=10, hidden_size=dim,
                           num_hidden_layers=hidden_layers,
                           num_attention_heads=attention_heads,
                           intermediate_size=intermediate_size))
            self.register_parameter("compress_token",
                                    torch.nn.Parameter(torch.randn([1, dim])))
            self.register_buffer("compress_mask", torch.ones([1, 1]))
            self.seq_model = BertEncoder(
                BertConfig(vocab_size=10, hidden_size=dim,
                           num_hidden_layers=hidden_layers,
                           num_attention_heads=attention_heads,
                           intermediate_size=intermediate_size))
            self.seq_embed = SettledPositionalEncoding(dim, seq_len)
            for idx in range(num_clf_tokens):
                self.register_parameter(
                    f"clf_token_{idx}",
                    torch.nn.Parameter(torch.randn([1, dim])))
            self.num_clf_tokens = num_clf_tokens
            self.seq_len = seq_len
            self.fcs = torch.nn.ModuleList([
                torch.nn.Linear(dim, od) for od in output_dims
            ])

        def forward(self, di, dm, cv, ci, cm, batch):
            emb = self.ebd_module(
                di.view(batch * self.seq_len, -1),
                dm.view(batch * self.seq_len, -1),
                cv.view(batch * self.seq_len, -1),
                ci.view(batch * self.seq_len, -1),
                cm.view(batch * self.seq_len, -1),
            )
            mask = torch.cat(
                [self.compress_mask.repeat(batch * self.seq_len, 1), emb[1]],
                dim=1)
            full_mask = (1.0 - mask[:, None, None, :]) * torch.finfo(torch.float).min
            compressed = self.compress_model(
                hidden_states=torch.cat(
                    [self.compress_token.repeat(batch * self.seq_len, 1, 1),
                     emb[0]], dim=1),
                attention_mask=full_mask
            ).last_hidden_state[:, 0, :]
            seq_embed = compressed.view(batch, self.seq_len, -1)
            positioned_seq_embed = self.seq_embed(seq_embed)
            clf_tokens = [self.get_parameter(f"clf_token_{i}").repeat(batch, 1, 1)
                          for i in range(self.num_clf_tokens)]
            last_layer = self.seq_model(
                hidden_states=torch.cat(
                    [positioned_seq_embed] + clf_tokens, dim=1)
            ).last_hidden_state
            outputs = []
            for i in range(self.num_clf_tokens):
                idx = -(i + 1)
                outputs.append(self.fcs[i](last_layer[:, idx, :]))
            if len(outputs) == 1:
                return outputs[0]
            return tuple(outputs)

    return WholeTransformer()


class SeqDataset(Dataset):

    def __init__(self, df, preprocess_func, seq_len, target_col='target'):
        self.datas = df
        self.preprocess_func = preprocess_func
        self.seq_len = seq_len
        self.target_col = target_col

    def __getitem__(self, index):
        part = self.datas.iloc[index:index + self.seq_len, :]
        dis_idx = []
        dis_mask = []
        con_value = []
        con_idx = []
        con_mask = []
        for i in range(self.seq_len):
            x = self.preprocess_func(part.iloc[i, :].to_dict())
            dis_idx.append(x['discrete_index'])
            dis_mask.append(x['discrete_mask'])
            con_value.append(x['continue_value'])
            con_idx.append(x['continue_index'])
            con_mask.append(x['continue_mask'])
        gt = self.datas[self.target_col].iloc[index + self.seq_len - 1]
        return (torch.stack(dis_idx), torch.stack(dis_mask),
                torch.stack(con_value), torch.stack(con_idx),
                torch.stack(con_mask), torch.tensor(gt, dtype=torch.float))

    def __len__(self):
        return self.datas.shape[0] - self.seq_len + 1

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor
from torch.autograd import Variable

from vqa.models import fusion
from .noatt import AbstractNoAtt


class RandomBaseline(nn.Module):

    def __init__(self, knn_size):
        super().__init__()

        self.knn_size = knn_size

    def forward(self, *args, **kwargs):
        batch_size = 1
        scores = Variable(torch.rand((batch_size, self.knn_size)))
        return F.softmax(scores, dim=1)


class DistanceBaseline(nn.Module):

    def __init__(self, knn_size):
        super().__init__()

        self.knn_size = knn_size

    def forward(self, *args, **kwargs):
        batch_size = 1
        scores = Variable(Tensor(list(reversed(range(self.knn_size)))).view(1, -1).expand((batch_size, self.knn_size)))
        return F.softmax(scores, dim=1)


# Returns the fusion vector in addition to the answer
class AbstractCX(AbstractNoAtt):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def forward(self, input_v, input_q):
        x_q = self.seq2vec(input_q)
        y = self._fusion(input_v, x_q)
        a = self._classif(y)
        return y, a


# Same as MutanNoAtt but inherits from AbstractCX
class MutanNoAttCX(AbstractCX):

    def __init__(self, opt={}, vocab_words=[], vocab_answers=[]):
        opt['fusion']['dim_h'] = opt['fusion']['dim_mm']
        super().__init__(opt, vocab_words, vocab_answers)
        self.fusion = fusion.MutanFusion(self.opt['fusion'])

    def _fusion(self, input_v, input_q):
        x = self.fusion(input_v, input_q)
        return x


class CXModel(nn.Module):

    def __init__(self, vqa_model, knn_size):
        super().__init__()

        self.vqa_model = vqa_model
        self.vqa_model.eval()

        self.knn_size = knn_size

    def forward(self, image_features, knn_features, question_wids, answer_aid):

        batch_size = 1

        # Process all image features as a single batch
        features_input = Variable(torch.cat([image_features, knn_features.view(batch_size * self.knn_size, -1)]))
        question_input = Variable(question_wids.expand(batch_size * (self.knn_size + 1), -1))

        y, a = self.vqa_model(features_input, question_input)
        a = a.view(batch_size, self.knn_size + 1, -1)

        # Unpack image features into original and knns
        a_orig = a[:, 0, :]
        y_orig = a[:, 0, :]

        a_knns = a[:, 1:, :]
        y_knns = a[:, 1:, :]

        # VQA model's score for the original answer for each KNN
        scores_list = []
        for i, a_idx in enumerate(answer_aid):
            scores_list.append(a_knns[i, :, a_idx])
        scores = torch.stack(scores_list, dim=0)

        # Flip the sign, since the highest scoring items are the worst counterexamples
        scores = -scores

        return F.softmax(scores, dim=1)


class QueryCXModel(nn.Module):

    def __init__(self, vqa_model, knn_size, dim_mm, dim_v):
        super().__init__()

        self.vqa_model = vqa_model
        self.vqa_model.eval()

        self.knn_size = knn_size
        self.dim_mm = dim_mm
        self.dim_v = dim_v

        self.linear = nn.Linear(dim_mm, dim_v)

    def forward(self, example):
        batch_size = example['orig']['idxs'].shape[0]

        y_orig, _ = self.vqa_model(Variable(example['orig']['v']), Variable(example['orig']['q']))
        y_orig = y_orig.detach()

        query = self.linear(y_orig)
        return query
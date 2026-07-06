package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.ImportQuestionEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * 导入题表访问 Mapper。
 *
 * <p>继承 MyBatis Plus {@link BaseMapper}，提供 {@link ImportQuestionEntity} 的基础 CRUD 能力。</p>
 */
@Mapper
public interface ImportQuestionMapper extends BaseMapper<ImportQuestionEntity> {
}

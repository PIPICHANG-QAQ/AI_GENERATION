package com.aigeneration.questionbank.domain.mapper;

import com.aigeneration.questionbank.domain.entity.AiJobEntity;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

/**
 * AI job 表访问 Mapper。
 *
 * <p>继承 MyBatis Plus {@link BaseMapper}，提供 {@link AiJobEntity} 的基础 CRUD 能力。</p>
 */
@Mapper
public interface AiJobMapper extends BaseMapper<AiJobEntity> {
}
